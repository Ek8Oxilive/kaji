"""Clé SÉPARÉE des jetons personnels (lot #440) : chargement, séparation d'avec `KAJI_SECRET_KEY`, rotation, et le critère « la base seule ne permet pas de lire un jeton »."""
import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import crypto, tokenkey
from app.config import Settings
from app.migrations import run_migrations
from app.models import UserToken
from app.tokenkey import TokenKeyError

SECRET = "la-cle-secrete-principale-de-kaji-0123456789abcdef"
KEY1 = "premiere-cle-des-jetons-personnels-0123456789abcdef"
KEY2 = "seconde-cle-des-jetons-personnels-0123456789abcdef"
TOKEN = "00000000-1111-2222-3333-444444444444"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, kaji_secret_key=SECRET, **kw)


def test_the_feature_is_off_without_a_key_and_never_raises_for_that():
    s = settings()
    assert tokenkey.load_key(s) is None and tokenkey.keys(s) == []
    with pytest.raises(TokenKeyError, match="non configurée"):
        tokenkey.encrypt(TOKEN, tokenkey.keys(s))


def test_a_short_example_or_identical_key_is_refused_without_echoing_it():
    for bad, why in (("courte", "trop courte"), ("changeme", "trop courte"), (SECRET, "DIFFÉRENTE")):
        with pytest.raises(TokenKeyError, match=why) as e:
            tokenkey.load_key(settings(kaji_token_key=bad))
        assert bad not in str(e.value) or bad == "courte"          # une clé valide d'exemple n'est jamais recopiée dans l'erreur
    with pytest.raises(TokenKeyError) as e:
        tokenkey.load_key(settings(kaji_token_key=SECRET))
    assert SECRET not in str(e.value)


def test_the_key_can_come_from_a_file_outside_the_environment(tmp_path):
    f = tmp_path / "token.key"; f.write_text(KEY1 + "\n")
    assert tokenkey.load_key(settings(kaji_token_key_file=str(f))) == KEY1
    assert tokenkey.load_key(settings(kaji_token_key=KEY1, kaji_token_key_file=str(f))) == KEY1      # même valeur des deux côtés : accepté
    with pytest.raises(TokenKeyError, match="valeurs différentes"):
        tokenkey.load_key(settings(kaji_token_key=KEY2, kaji_token_key_file=str(f)))
    with pytest.raises(TokenKeyError, match="illisible") as e:
        tokenkey.load_key(settings(kaji_token_key_file=str(tmp_path / "absent.key")))
    assert KEY1 not in str(e.value)


def test_round_trip_and_wrong_key_and_tampering():
    blob = tokenkey.encrypt(TOKEN, [KEY1])
    assert TOKEN not in blob and tokenkey.decrypt(blob, [KEY1]) == TOKEN
    with pytest.raises(TokenKeyError) as e:
        tokenkey.decrypt(blob, [KEY2])
    assert TOKEN not in str(e.value) and KEY2 not in str(e.value)
    with pytest.raises(TokenKeyError):
        tokenkey.decrypt(blob[:-4] + "AAAA", [KEY1])
    assert tokenkey.readable(blob, [KEY1]) and not tokenkey.readable(blob, [KEY2]) and not tokenkey.readable(None, [KEY1])


def test_the_token_key_derivation_is_distinct_from_the_data_key_derivation():
    """Même chaîne comme clé des deux côtés : les chiffrés restent mutuellement illisibles (étiquettes de dérivation différentes)."""
    shared = KEY1
    assert not _opens(crypto.decrypt, shared, tokenkey.encrypt(TOKEN, [shared]))
    other = crypto.encrypt(shared, TOKEN)
    with pytest.raises(TokenKeyError):
        tokenkey.decrypt(other, [shared])


def _opens(fn, key, blob) -> bool:
    try:
        fn(key, blob)
        return True
    except ValueError:
        return False


def test_rotation_reads_with_both_keys_and_rewrites_with_the_first():
    old = tokenkey.encrypt(TOKEN, [KEY2])
    both = [KEY1, KEY2]
    assert tokenkey.decrypt(old, both) == TOKEN                       # la fenêtre de rotation : l'ancien chiffré se lit encore
    new = tokenkey.rotate(old, both)
    assert tokenkey.decrypt(new, [KEY1]) == TOKEN                     # la nouvelle clé SEULE suffit
    assert not tokenkey.readable(new, [KEY2])                         # et l'ancienne ne lit plus le résultat
    with pytest.raises(TokenKeyError):
        tokenkey.rotate(tokenkey.encrypt(TOKEN, ["une-troisieme-cle-inconnue-0123456789abcdef"]), both)
    s = settings(kaji_token_key=KEY1, kaji_token_key_previous=KEY2)
    assert tokenkey.keys(s) == [KEY1, KEY2]
    assert tokenkey.keys(settings(kaji_token_key=KEY1, kaji_token_key_previous=KEY1)) == [KEY1]       # doublon écarté


def test_the_database_alone_does_not_let_anyone_read_a_personal_token(tmp_path):
    """CRITÈRE DE SORTIE de #440 : avec le fichier de base ET `KAJI_SECRET_KEY` (le contenu de `.env` et de la sauvegarde), le jeton reste illisible ; avec la clé séparée il se lit."""
    path = tmp_path / "kaji.db"
    engine = create_engine(URL.create("sqlite", database=str(path)))
    run_migrations(engine)
    with Session(engine) as db:
        db.add(UserToken(user_id=1, conn_id=1, pve_user="alice@pve", token_id="kaji-alice", secret_enc=tokenkey.encrypt(TOKEN, [KEY1]),
                         expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc), privsep=True, verified=True))
        db.commit()
    engine.dispose()
    raw = path.read_bytes()
    assert TOKEN.encode() not in raw and KEY1.encode() not in raw                           # ni le jeton ni la clé dans le fichier
    blob = sqlite3.connect(path).execute("SELECT secret_enc FROM user_tokens").fetchone()[0]
    assert not _opens(crypto.decrypt, SECRET, blob)                                         # KAJI_SECRET_KEY ne l'ouvre pas
    for guess in (SECRET, KEY2, "", "changeme"):
        assert not tokenkey.readable(blob, [guess]) or guess == ""                          # une mauvaise clé non plus (la clé vide est refusée avant)
    with pytest.raises(TokenKeyError):
        tokenkey.decrypt(blob, [])                                                          # sans clé configurée : rien
    assert tokenkey.decrypt(blob, [KEY1]) == TOKEN                                          # seule la clé séparée l'ouvre
