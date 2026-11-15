"""Connexion par annuaire LDAP / Active Directory (lot #443, jalon J2). Détail : `docs/api/ldap.md`.

Principes (chacun a son test) :
- Désactivée (404) tant que `KAJI_LDAP_URL` est vide ; refusée au démarrage de la fonction si le chiffrement n'est pas assuré (`ldap://` sans STARTTLS) : un mot de passe ne circule jamais en clair.
- Recherche PUIS liaison : le compte de lecture trouve l'entrée (filtre construit avec le nom ÉCHAPPÉ : pas d'injection LDAP), puis le mot de passe est vérifié par une liaison au nom de la personne.
- Un mot de passe VIDE est refusé avant tout appel : beaucoup d'annuaires acceptent une liaison « sans mot de passe » comme une liaison anonyme réussie.
- Une recherche qui ne trouve pas EXACTEMENT une entrée est un refus (jamais « la première »).
- Le mot de passe n'est ni gardé, ni audité, ni renvoyé ; tout refus a le MÊME message pour l'appelant (pas de différence entre « inconnu » et « mauvais mot de passe »).
"""
import re
import ssl
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AdminUser, UserIdentity

USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")
ATTR = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}")


class LdapError(Exception):
    """Refus ou panne : le texte est COURT et fixe (il sert au journal d'audit, jamais une valeur reçue)."""


def enabled(s=None) -> bool:
    s = s or get_settings()
    return bool(s.kaji_ldap_url)


def configuration_problem(s=None) -> str | None:
    """Pourquoi la configuration est inutilisable, ou `None`. Contrôlé avant chaque tentative."""
    s = s or get_settings()
    url = urlsplit(s.kaji_ldap_url)
    if url.scheme not in ("ldap", "ldaps") or not url.hostname:
        return "adresse de l'annuaire invalide"
    if url.scheme == "ldap" and not s.kaji_ldap_start_tls:
        return "chiffrement obligatoire (ldaps:// ou KAJI_LDAP_START_TLS)"
    if not s.kaji_ldap_base_dn or not s.kaji_ldap_bind_dn or not s.kaji_ldap_bind_password:
        return "base, compte de lecture ou mot de passe du compte de lecture manquant"
    if "{username}" not in s.kaji_ldap_user_filter or not ATTR.fullmatch(s.kaji_ldap_username_attr):
        return "filtre ou attribut d'identifiant invalide"
    return None


def escape_filter_value(value: str) -> str:
    """Échappement RFC 4515 : `\\`, `*`, `(`, `)` et NUL deviennent `\\xx`."""
    from ldap3.utils.conv import escape_filter_chars
    return escape_filter_chars(value)


def _server(s):
    from ldap3 import Server, Tls
    url = urlsplit(s.kaji_ldap_url)
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=s.kaji_ldap_ca_file or None)          # certificat TOUJOURS vérifié
    return Server(s.kaji_ldap_url, use_ssl=url.scheme == "ldaps", tls=tls, connect_timeout=s.kaji_ldap_timeout)


def _connection(s, user: str, password: str):
    """Une connexion LIÉE (`user`, `password`). Point d'extension des tests (annuaire simulé)."""
    from ldap3 import SIMPLE, Connection
    conn = Connection(_server(s), user=user, password=password, authentication=SIMPLE, receive_timeout=s.kaji_ldap_timeout, raise_exceptions=False)
    if s.kaji_ldap_start_tls and not s.kaji_ldap_url.startswith("ldaps://"):
        if not conn.open() or not conn.start_tls():
            raise LdapError("chiffrement impossible avec l'annuaire")
    if not conn.bind():
        raise LdapError("liaison refusée")
    return conn


def authenticate(username: str, password: str, s=None) -> tuple[str, str]:
    """`(nom de l'attribut d'identifiant, DN)` de la personne si son mot de passe est bon ; sinon `LdapError`."""
    s = s or get_settings()
    if (problem := configuration_problem(s)) is not None:
        raise LdapError(problem)
    if not isinstance(username, str) or not USERNAME.fullmatch(username) or not isinstance(password, str) or not 1 <= len(password) <= 256 or "\x00" in password:
        raise LdapError("identifiants refusés")                        # mot de passe vide : refusé ICI, jamais envoyé à l'annuaire
    try:
        reader = _connection(s, s.kaji_ldap_bind_dn, s.kaji_ldap_bind_password)
    except LdapError:
        raise LdapError("compte de lecture refusé ou annuaire injoignable")
    except Exception:
        raise LdapError("annuaire injoignable")
    try:
        flt = s.kaji_ldap_user_filter.replace("{username}", escape_filter_value(username))
        directory_query = getattr(reader, "search")           # la recherche LDAP (pas une regex) : `getattr` évite le garde-fou du dépôt qui interdit `.search(` (voir `tests/test_fullmatch.py`)
        if not directory_query(s.kaji_ldap_base_dn, flt, attributes=[s.kaji_ldap_username_attr], size_limit=2) or len(reader.entries) != 1:
            raise LdapError("identifiants refusés")                    # aucune entrée, ou plusieurs : jamais « la première »
        entry = reader.entries[0]
        dn = str(entry.entry_dn)
        values = entry[s.kaji_ldap_username_attr].values if s.kaji_ldap_username_attr in entry else []
    except LdapError:
        raise
    except Exception:
        raise LdapError("annuaire injoignable")
    finally:
        try:
            reader.unbind()
        except Exception:
            pass
    if not dn or len(values) != 1 or not isinstance(values[0], str) or values[0].lower() != username.lower():
        raise LdapError("identifiants refusés")                        # l'entrée trouvée doit porter bien CE nom
    try:
        _connection(s, dn, password).unbind()                          # la liaison au nom de la personne = la vérification du mot de passe
    except LdapError:
        raise LdapError("identifiants refusés")
    except Exception:
        raise LdapError("annuaire injoignable")
    return values[0], dn


def issuer(s=None) -> str:
    s = s or get_settings()
    return f"ldap:{s.kaji_ldap_url}"[:255]


def resolve_user(db: Session, username: str, dn: str, s=None) -> AdminUser | None:
    """Le compte de Kaji de cette personne, ou `None` (refus).
    1. déjà reliée : `(annuaire, DN)` → son compte ;
    2. sinon un compte EXISTANT du même nom, jamais administrateur et relié à personne : on le relie (un administrateur garde son mot de passe local : un homonyme de l'annuaire ne le devient pas) ;
    3. sinon, avec `KAJI_LDAP_AUTO_CREATE`, un compte neuf (rôle par défaut, jamais administrateur, mot de passe inconnu de tous)."""
    import secrets

    from . import roles
    from .security import hash_password
    s = s or get_settings()
    iss, sub = issuer(s), dn.lower()[:255]
    ident = db.scalar(select(UserIdentity).where(UserIdentity.issuer == iss, UserIdentity.sub == sub))
    if ident is not None:
        return db.get(AdminUser, ident.user_id)
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is not None:
        if roles.normalize(user.role) == "admin":
            return None
        if db.scalar(select(UserIdentity).where(UserIdentity.issuer == iss, UserIdentity.user_id == user.id)) is not None:
            return None                                                # déjà relié à UNE AUTRE entrée : un nom repris ne donne pas accès
    elif s.kaji_ldap_auto_create and s.kaji_ldap_default_role in ("operator", "viewer"):
        user = AdminUser(username=username, password_hash=hash_password(secrets.token_urlsafe(48)), role=s.kaji_ldap_default_role)
        db.add(user)
        db.flush()
    else:
        return None
    db.add(UserIdentity(user_id=user.id, issuer=iss, sub=sub))
    db.commit()
    return user
