from datetime import datetime, timedelta

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.auth import create_or_update_user
from llm_freeway.database import EventLog, get_session
from llm_freeway.settings import Settings

env = Settings()


@pytest.fixture(name="session")
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def get_session_override(session):
    def f():
        return session

    return f


@pytest.fixture()
def client(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def payload():
    yield {
        "model": "azure/gpt-4o",
        "messages": [{"role": "user", "content": "hello :)"}],
        "mock_response": "hello, how can i help you?",
    }


@pytest.fixture
def admin_user(session):
    usr = create_or_update_user(
        "some.one@department.gov.uk", "admin", True, 10_000, session
    )
    yield usr
    session.delete(usr)
    session.commit()


@pytest.fixture
def user(session):
    usr = create_or_update_user(
        "an.other@department.gov.uk", "admin", False, 1_000, session
    )
    yield usr
    session.delete(usr)
    session.commit()


@pytest.fixture
def user_with_spend(user, session):
    now = datetime.now()
    events = [
        EventLog(
            timestamp=now - timedelta(seconds=seconds),
            response_id="1",
            user_id=user.id,
            model="a-model",
            prompt_tokens=200,
            completion_tokens=100,
        )
        for seconds in range(120)
    ]
    for event in events:
        session.add(event)
    session.commit()
    yield user
    for event in events:
        session.delete(event)
    session.commit()
