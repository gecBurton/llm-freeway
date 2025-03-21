from datetime import datetime, timedelta

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.auth import create_user_db
from llm_freeway.database import LLM, EventLog, get_session
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
def payload(gpt_4o):
    yield {
        "model": gpt_4o.name,
        "messages": [{"role": "user", "content": "hello :)"}],
        "mock_response": "hello, how can i help you?",
    }


@pytest.fixture
def admin_user_password():
    yield "admin"


@pytest.fixture
def admin_user(session, admin_user_password):
    usr = create_user_db(
        "some.one@department.gov.uk", admin_user_password, True, 10_000, session
    )
    yield usr
    session.delete(usr)
    session.commit()


@pytest.fixture
def user(session):
    usr = create_user_db("an.other@department.gov.uk", "admin", False, 1_000, session)
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
            cost_usd=0.1,
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


@pytest.fixture
def user_with_low_rate_high_spend(user, session):
    now = datetime.now()
    event = EventLog(
        timestamp=now - timedelta(seconds=1),
        response_id="1",
        user_id=user.id,
        model="a-model",
        prompt_tokens=200,
        completion_tokens=100,
        cost_usd=1_000,
    )
    session.add(event)
    session.commit()
    yield user
    session.delete(event)
    session.commit()


@pytest.fixture
def gpt_4o(session):
    llm = LLM(name="gpt-4o", input_cost_per_token=0.1, output_cost_per_token=0.2)
    session.add(llm)
    session.commit()
    session.refresh(llm)
    yield llm
    session.delete(llm)
    session.commit()


@pytest.fixture
def gpt_4o_mini(session):
    llm = LLM(name="gpt-4o-mini", input_cost_per_token=0.1, output_cost_per_token=0.2)
    session.add(llm)
    session.commit()
    session.refresh(llm)
    yield llm
    session.delete(llm)
    session.commit()
