# V1 : les actions à faire à la main, pas à pas (Enzo, avec PC A)

Ces quatre étapes touchent la configuration système ou la sécurité (jeton, nœud, HTTPS) : **les agents ne les font pas, même sur demande**. Tu tapes, **PC A vérifie après chaque étape, en lecture seule**. Aucune valeur secrète ne passe par le chat : PC A n'a besoin d'aucun mot de passe ni jeton.

**Ordre conseillé** : A (jeton, 5 min) → B (dépôt en doublon, 5 min) → C (relais SMTP, 30 min) → D (HTTPS, facultatif, 20 min, en dernier).
**Non testé par les agents** : aucune de ces commandes n'a été lancée sur ton cluster par un agent. Chaque étape a donc un retour arrière.

## Avant de commencer
- **Accès de secours au CT 116** qui ne passe pas par Kaji : interface Proxmox (`https://<nœud>:8006`) → `enzo` → machine 116 → **Console**. La console de Kaji se coupe dès que Kaji redémarre (étapes A et D).
- **Sauvegarde du CT 116** avant l'étape D : Proxmox → 116 → Sauvegarde → « Sauvegarder maintenant ».
- Garde les valeurs secrètes (jeton, mot de passe SMTP) dans ton gestionnaire de mots de passe, jamais dans le chat ni dans un fichier du dépôt.

---

## Étape A : jeton de première configuration (`KAJI_SETUP_TOKEN`)
**À quoi ça sert** : tant qu'aucun compte administrateur n'existe, l'écran de première configuration exige ce jeton. Ton compte existe déjà, donc l'étape ne coupe rien ; elle protège une réinstallation.

**Tu fais** (terminal du CT 116, dossier `~/kaji`) :
1. `cp .env .env.bak-$(date +%Y%m%d)`
2. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` → copie le résultat dans ton gestionnaire de mots de passe.
3. Édite `.env` : une seule ligne `KAJI_SETUP_TOKEN=<la valeur>` (sans guillemets).
4. Recrée le backend, **détaché** (la console va se couper) :
   `nohup sh -c 'cd ~/kaji && docker compose up -d --force-recreate backend' > /root/recreate.log 2>&1 &`
   (un simple `restart` ne relit pas `.env`). Rouvre ensuite le terminal.
5. Contrôle sans afficher le jeton : `docker compose exec -T backend sh -c 'test -n "$KAJI_SETUP_TOKEN" && echo défini || echo absent'` → doit répondre `défini`.

**PC A vérifie** : `/api/health` répond 200 et ta session est toujours valide. **Limite** : `GET /api/auth/status` n'affiche `setup_token_required` que s'il n'existe aucun compte ; ici il restera `false` même si le jeton est défini. La seule preuve est donc la commande de l'étape 5.

**Retour arrière** : `cp .env.bak-<date> .env` puis la même commande de recréation.

---

## Étape B : supprimer le dépôt apt en doublon sur `enzo2`
**Contexte** : `/etc/apt/sources.list.d/pve-no-subscription.list` (suite `bookworm`) est un reste obsolète de `proxmox.sources` (suite `trixie`). Kaji sait désactiver un dépôt, pas supprimer le fichier.

**Tu fais** (Proxmox → `enzo2` → **Shell**) :
1. `ls -l /etc/apt/sources.list.d/`
2. `cat /etc/apt/sources.list.d/pve-no-subscription.list` : doit parler de `bookworm`.
   `cat /etc/apt/sources.list.d/proxmox.sources` : doit parler de `trixie` et `pve-no-subscription`. **Si ce n'est pas le cas, arrête-toi et dis-le moi.**
3. `cp -a /etc/apt/sources.list.d/pve-no-subscription.list /root/pve-no-subscription.list.bak`
4. `rm /etc/apt/sources.list.d/pve-no-subscription.list`
5. `apt update` : plus d'avertissement « configured multiple times », aucune erreur.

**PC A vérifie** : page Nœud `enzo2` → section « Dépôts de paquets » (lecture) : le fichier `.list` n'apparaît plus, `proxmox.sources` reste actif. Aucune écriture de ma part.

**Retour arrière** : `cp -a /root/pve-no-subscription.list.bak /etc/apt/sources.list.d/pve-no-subscription.list`.

---

## Étape C : relais SMTP sortant, puis test de la cible `kaji-test`
**Contexte** : Postfix de `enzo` envoie en direct sur le port 25, bloqué (timeout), et IPv6 est inaccessible ; **6 messages attendent en file depuis le 6 novembre**. Il faut un relais authentifié (OVH ou SMTP Proton : à décider). **Les noms de serveur, le port et le type d'identifiant se lisent chez le fournisseur** : ils ne sont pas inventés ici (Proton, par exemple, demande un jeton SMTP dédié).

**Deux options, à choisir avant de commencer** :
- **Option 1 (recommandée)** : relais Postfix sur `enzo` puis `enzo2`. Il règle **tous** les mails du nœud (alertes, sauvegardes, notifications `sendmail`, cible `kaji-test`).
- **Option 2** : une cible **SMTP** dans Datacenter → Notifications. Elle ne règle que les notifications, pas les mails système. Le mot de passe se tape **toi-même** dans le formulaire (champ en écriture seule).

**Tu fais, option 1, sur chaque nœud** (Shell du nœud) :
1. État avant : `postconf -n | grep -E 'relayhost|smtp_sasl'` ; `cp /etc/postfix/main.cf /root/main.cf.bak` ; `postqueue -p | tail -n 3`.
2. `apt install libsasl2-modules` (si absent).
3. `nano /etc/postfix/sasl_passwd` : une ligne `[serveur.du.fournisseur]:587 identifiant:motdepasse`, puis
   `chmod 600 /etc/postfix/sasl_passwd && postmap /etc/postfix/sasl_passwd`
4. Réglages (remplace le serveur et le port par ceux du fournisseur) :
   ```
   postconf -e 'relayhost = [serveur.du.fournisseur]:587'
   postconf -e 'smtp_sasl_auth_enable = yes'
   postconf -e 'smtp_sasl_security_options = noanonymous'
   postconf -e 'smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd'
   postconf -e 'smtp_tls_security_level = encrypt'
   postconf -e 'smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt'
   systemctl restart postfix
   ```
   (port 465 : `smtp_tls_wrappermode = yes` en plus ; vérifie chez le fournisseur.)
5. Test : `printf 'Subject: test relais\n\ntest\n' | sendmail toi@exemple.fr`, puis `journalctl -u postfix -n 30 --no-pager` : cherche `status=sent`.
6. **File d'attente** : les 6 anciens messages partiront au prochain passage. **À toi de décider** : les laisser partir (`postqueue -f`), ou les supprimer. **Je ne vide jamais la file.**

**PC A fait / vérifie, avec ton accord explicite sur l'adresse** : Kaji → Datacenter → Notifications → cible `kaji-test` → « Tester » : c'est un **vrai message** (nom de la cible retapé). Tu me confirmes la réception. Puis **suppression de `kaji-test`** (nom retapé) **seulement quand tu me le dis à ce moment-là**, pour revenir à `mail-to-root` seule.

**Retour arrière** : `cp /root/main.cf.bak /etc/postfix/main.cf`, supprime `/etc/postfix/sasl_passwd` et `/etc/postfix/sasl_passwd.db`, `systemctl restart postfix`.

---

## Étape D : HTTPS avec Caddy (facultatif, en dernier)
**À décider d'abord** : Kaji est aujourd'hui joint en HTTP par le VPN. Rester ainsi est défendable pour la V1 **si l'annonce le dit** (« accès par VPN uniquement »). Le HTTPS Caddy est fourni mais **n'a jamais été testé en réel**. Ne le fais que si tu as l'accès de secours ci-dessus **et** la sauvegarde du CT 116.

**Piège** : avec `KAJI_COOKIE_SECURE=true`, la connexion en HTTP ne garde plus de session. L'ancien accès ne sert donc plus de secours : le retour arrière passe par `.env`.

**Tu fais** (terminal du CT 116, `~/kaji`) :
1. `cp .env .env.bak-https-$(date +%Y%m%d)` ; `grep -E 'KAJI_COOKIE_SECURE|KAJI_BIND|KAJI_TLS_SITE' .env` (note l'état de départ).
2. Dans `.env` : `KAJI_COOKIE_SECURE=true`, `KAJI_TLS_SITE=<adresse de Kaji>:8443` (l'adresse par laquelle tu ouvres Kaji), et **garde `KAJI_BIND` tel quel** pour l'instant.
3. Lance, **détaché** (la console va se couper ; continue depuis la console de Proxmox) :
   `nohup sh -c 'cd ~/kaji && docker compose down && docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build' > /root/tls.log 2>&1 &`
   puis `tail -n 30 /root/tls.log` : le build doit finir sans erreur.
4. Récupère l'autorité de Caddy : `docker compose -f docker-compose.yml -f docker-compose.tls.yml cp tls:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt`, puis installe `caddy-root.crt` comme autorité de confiance dans ton navigateur. **C'est une décision de confiance** : cette autorité sert uniquement à Kaji ; sauvegarde le volume `caddy-data` (sa clé).
5. Ouvre `https://<adresse>:8443`, connecte-toi, page Connexions → « Tester ».
6. Une fois que tout marche, **seulement alors**, `KAJI_BIND=127.0.0.1` dans `.env` pour fermer le port 8080, et recrée avec la même commande qu'à l'étape 3.

**PC A vérifie** : `/api/health` et `/api/auth/status` répondent en HTTPS, le cookie de session est `Secure`, la connexion Proxmox testée par Kaji répond OK, l'épingle du certificat est inchangée, et le limiteur de connexions voit bien l'adresse du client (pas celle du proxy).

**Retour arrière** : `cp .env.bak-https-<date> .env`, puis `nohup sh -c 'cd ~/kaji && docker compose -f docker-compose.yml -f docker-compose.tls.yml down && docker compose up -d --build' > /root/tls-undo.log 2>&1 &`.

---

## Ensuite
- **Annonce V1** : l'épinglage du certificat est fait et vérifié (le 2026-11-13). Les étapes A et D conditionnent surtout le texte de l'annonce ; B et C n'empêchent pas la V1.
- Dis-moi « étape X faite » : je lance les vérifications de la section correspondante et je te donne un compte rendu court.
