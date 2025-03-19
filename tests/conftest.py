import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.auth import create_or_update_user
from src.settings import Settings

env = Settings()


@pytest.fixture
def engine():
    _engine = create_engine(
        # "sqlite:///:memory:",
        "sqlite:///test.db",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(_engine)
    yield _engine


@pytest.fixture
def get_session_override(engine):
    def f():
        with Session(engine) as session:
            yield session

    return f


@pytest.fixture
def session(engine):
    with Session(engine) as _session:
        yield _session


@pytest.fixture
def payload():
    yield {
        "model": "azure/gpt-4o",
        "messages": [{"role": "user", "content": "hello :)"}],
        "mock_response": "hello, how can i help you?",
    }


@pytest.fixture
def admin_user(session):
    usr = create_or_update_user("some.one@department.gov.uk", "admin", True, session)
    yield usr
    session.delete(usr)
    session.commit()


@pytest.fixture
def user(session):
    usr = create_or_update_user("an.other@department.gov.uk", "admin", False, session)
    yield usr
    session.delete(usr)
    session.commit()
