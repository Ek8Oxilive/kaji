from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.crypto import encrypt
from app.db import Base
from app.models import Connection


def test_connection_stores_encrypted_secret():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Connection(name="test", host="10.0.0.1", user="pud@pve", token_id="pud",
                         token_secret_enc=encrypt("k" * 20, "abc123")))
        s.commit()
        row = s.scalars(select(Connection)).one()
        assert row.token_secret_enc != "abc123"
        assert row.port == 8006
