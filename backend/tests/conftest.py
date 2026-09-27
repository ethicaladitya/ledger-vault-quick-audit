import os, sys
from pathlib import Path

DB = Path(__file__).parent / ".test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db():
    from app.database import Base, engine, SessionLocal
    from app import migrate
    Base.metadata.drop_all(engine)
    migrate.run()
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client(db, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ALLOW_REGISTRATION", True)
    with TestClient(main.app) as c:
        yield c


def signup(client, email="owner@example.com"):
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery", "full_name": "Test Owner"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
