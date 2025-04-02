from datetime import datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.auth import get_current_user
from llm_freeway.database import LLM, EventLog, LLMConfig, User, get_models, get_session


@pytest.fixture(name="session")
def session():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def get_session_override(session):
    def f():
        return session

    return f


@pytest.fixture
def get_models_override(gpt_4o, gpt_4o_mini):
    def f():
        return LLMConfig(models=[gpt_4o, gpt_4o_mini])

    return f


@pytest.fixture
def get_current_user_override(normal_user):
    def f():
        return normal_user

    return f


@pytest.fixture()
def client(get_session_override, get_models_override, get_current_user_override):
    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_models] = get_models_override
    app.dependency_overrides[get_current_user] = get_current_user_override

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
def normal_user(admin_user_password):
    user = User(
        id=uuid4(),
        username="an.other@department.gov.uk",
        password=admin_user_password,
        is_admin=False,
        requests_per_minute=60,
        tokens_per_minute=1_000,
        cost_usd_per_month=10,
    )

    yield user


@pytest.fixture
def user_with_spend(normal_user, session, gpt_4o):
    now = datetime.now()
    events = [
        EventLog(
            timestamp=now - timedelta(seconds=seconds),
            response_id="1",
            user_id=normal_user.id,
            model=gpt_4o.name,
            prompt_tokens=200,
            completion_tokens=100,
            cost_usd=0.1,
        )
        for seconds in range(120)
    ]
    for event in events:
        session.add(event)
    session.commit()
    yield normal_user
    for event in events:
        session.delete(event)
    session.commit()


@pytest.fixture
def user_with_high_tokens_low_spend(normal_user, session, gpt_4o):
    now = datetime.now()
    events = [
        EventLog(
            timestamp=now,
            response_id="1",
            user_id=normal_user.id,
            model=gpt_4o.name,
            prompt_tokens=200,
            completion_tokens=100,
            cost_usd=0,
        )
        for _ in range(60)
    ]
    for event in events:
        session.add(event)
    session.commit()
    yield normal_user
    for event in events:
        session.delete(event)
    session.commit()


@pytest.fixture
def user_with_high_rate_low_spend(normal_user, session, gpt_4o):
    now = datetime.now()
    events = [
        EventLog(
            timestamp=now,
            response_id="1",
            user_id=normal_user.id,
            model=gpt_4o.name,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0,
        )
        for _ in range(100)
    ]
    for event in events:
        session.add(event)
    session.commit()
    yield normal_user
    for event in events:
        session.delete(event)
    session.commit()


@pytest.fixture
def user_with_low_rate_high_spend(normal_user, session, gpt_4o):
    now = datetime.now()
    event = EventLog(
        timestamp=now - timedelta(seconds=1),
        response_id="1",
        user_id=normal_user.id,
        model=gpt_4o.name,
        prompt_tokens=200,
        completion_tokens=100,
        cost_usd=1_000,
    )
    session.add(event)
    session.commit()
    yield normal_user
    session.delete(event)
    session.commit()


@pytest.fixture
def gpt_4o():
    llm = LLM(name="gpt-4o", input_cost_per_token=0.1, output_cost_per_token=0.2)
    yield llm


@pytest.fixture
def gpt_4o_mini():
    llm = LLM(name="gpt-4o-mini", input_cost_per_token=0.1, output_cost_per_token=0.2)
    yield llm


def get_headers(user: User) -> dict[str, str]:
    payload = user.model_dump()
    payload["sub"] = str(payload.pop("id"))
    token = jwt.encode(payload, "secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
