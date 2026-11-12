# Serveurs NTP d'un nœud (commandes à copier)

**Kaji n'appelle pas Proxmox pour cette fonction.** L'API de Proxmox VE 9 n'a aucune route NTP : `/nodes/{n}/time` n'accepte que `timezone`
(`apidoc.js`, vérifié le 2026-11-12). La synchronisation se règle dans `chrony`, sur le nœud. Comme pour les dépôts apt libres
(`docs/api/depot-apt-perso.md`), Kaji valide les champs et fabrique ce qu'il faut coller dans la console du nœud (bouton « Serveurs NTP… » du bloc
« Configuration du nœud » de la page Nœud). Redémarrer le service `chrony` reste possible depuis Kaji (section Services, validé en réel).

| Route | Corps | Résultat |
|---|---|---|
| `POST …/nodes/{n}/ntp/commands` | `{name, sources: [{host, kind?, iburst?, nts?}]}` | `{file, content, commands, warnings}` (aucun appel Proxmox, aucune écriture) |

## Champs (liste blanche, jamais de texte libre)
- `name` : `^[a-z0-9][a-z0-9-]{0,59}$` → fichier `/etc/chrony/sources.d/<name>.sources`.
- `sources` : 1 à 4, sans doublon (insensible à la casse). `host` : nom d'hôte (étiquettes alphanumériques et tirets, pas de point final, **pas de dernière étiquette numérique** : « 1.1.1.256 » est refusé) ou adresse IP valide **sans identifiant de zone** (`%`). `kind` : `server` (défaut) ou `pool` (nom d'hôte seulement, jamais une IP). `iburst` (vrai par défaut), `nts` (faux). Aucune autre option de `chrony` : un champ inconnu est ignoré, jamais copié.

## Résultat
- `content` : une ligne par source, ex. `pool 0.fr.pool.ntp.org iburst` ou `server time.example.org iburst nts`.
- `commands`, dans l'ordre : `grep -E '^sourcedir /etc/chrony/sources.d' /etc/chrony/chrony.conf` (contrôle), `cat > <fichier> <<'KAJI_EOF' … KAJI_EOF` (délimiteur entre guillemets : le shell n'interprète rien), `chronyc reload sources`, `chronyc sources -v` (vérification).
- `warnings` : la première commande doit afficher la ligne `sourcedir` (sinon le nœud n'a pas la configuration Debian habituelle : ne rien écrire), NTS (le serveur doit le proposer), pas d'`iburst`, adresse du réseau local.

**Limite honnête** : le format (`sourcedir /etc/chrony/sources.d`, fichiers `*.sources`) est celui de Debian ; Kaji ne peut pas relire la configuration du nœud et **ne l'a pas vu en réel** sur `enzo`. D'où la commande de contrôle en premier.
Pas d'entrée d'audit (aucune écriture, aucun secret). Tests : `backend/tests/test_ntp_commands.py` (38 cas, 18 mutations tuées).
