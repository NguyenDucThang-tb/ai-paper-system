import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import deps
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.api.v1.api_router import api_router
from app.models.user import User
import app.crud.user as crud_user

app = FastAPI()
app.include_router(api_router, prefix="/api/v1")


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def test_session_local(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture()
def db_session(test_session_local):
    db = test_session_local()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture(autouse=True)
def override_internal_token():
    settings.INTERNAL_API_TOKEN = "test-internal-token"
    yield


@pytest.fixture(autouse=True)
def fast_password_hash(monkeypatch):
    monkeypatch.setattr(crud_user, "get_password_hash", lambda p: f"hashed::{p}")
    monkeypatch.setattr(crud_user, "verify_password", lambda p, h: h == f"hashed::{p}")
    yield


@pytest.fixture()
def default_user(db_session):
    user = User(
        email=f"tester-{uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Tester",
        is_active=True,
        role="user",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def client(test_session_local, default_user) -> Generator[TestClient, None, None]:
    def _override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    def _override_current_user():
        return default_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[deps.get_current_user] = _override_current_user

    c = TestClient(app)
    yield c
    c.close()

    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(test_session_local) -> Generator[TestClient, None, None]:
    def _override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    c = TestClient(app)
    yield c
    c.close()

    app.dependency_overrides.clear()
