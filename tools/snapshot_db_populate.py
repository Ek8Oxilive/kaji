"""Remplit une base avec des données d'exemple en utilisant le code de la VERSION COURANTE DU DOSSIER (appelé par `tools/snapshot_db.py` dans un worktree de l'ancienne version).

Ne dépend que de ce qui existait dans toutes les versions : les modèles et colonnes plus récents sont ignorés s'ils n'existent pas. Toutes les valeurs sont FICTIVES et la clé est
celle des tests (`FIXTURE_KEY`) : ces bases sont publiques, elles ne contiennent aucun vrai secret.
"""
import sys

from sqlalchemy.orm import Session

from app import models
from app.crypto import encrypt
from app.db import get_engine, init_db
from app.security import hash_password

FIXTURE_KEY, PASSWORD = sys.argv[1], sys.argv[2]
TOKEN, HOOK = "jeton-fictif-0123456789", "https://hooks.example.org/services/FICTIF-WEBHOOK"

init_db()
with Session(get_engine()) as db:
    def make(cls, **fields):
        return cls(**{k: v for k, v in fields.items() if hasattr(cls, k)})
    db.add(make(models.AdminUser, username="alice", password_hash=hash_password(PASSWORD), role="admin"))
    db.add(make(models.AdminUser, username="bob", password_hash=hash_password(PASSWORD), role="operator"))
    db.add(make(models.Connection, name="lab", host="10.0.0.5", port=8006, user="kaji@pve", token_id="kaji", token_secret_enc=encrypt(FIXTURE_KEY, TOKEN),
                verify_ssl=False, tls_cert_pem="-----BEGIN CERTIFICATE-----\nFICTIF\n-----END CERTIFICATE-----"))
    db.flush()
    if hasattr(models, "AlertRule"):
        db.add(make(models.AlertRule, conn_id=1, name="cpu", kind="cpu", threshold=90, minutes=5, enabled=True, webhook_enc=encrypt(FIXTURE_KEY, HOOK), created_by="alice"))
        db.add(make(models.AlertRule, conn_id=1, name="mem", kind="mem", threshold=85, minutes=10, enabled=False, created_by="alice"))
    if hasattr(models, "ScheduledAction"):
        db.add(make(models.ScheduledAction, conn_id=1, node="n1", gtype="qemu", vmid=115, action="start", days="0,1,2", time="08:00", enabled=True, created_by="alice"))
    for i in range(3):
        db.add(make(models.AuditLog, username="alice", action="exemple", target=f"vm:{100 + i}", status="started", connection_id=1))
    db.commit()
print("base d'exemple remplie")
