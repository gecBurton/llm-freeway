from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from keycloak import KeycloakAdmin, KeycloakOpenID, KeycloakOpenIDConnection
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.auth import get_token
from llm_freeway.database import (
    LLM,
    EventLog,
    KeycloakUser,
    SQLUser,
    User,
    get_session,
    pwd_context,
)
from llm_freeway.settings import KeycloakSettings, env


class BaseUserManager:
    def create(self, **kwargs) -> SQLUser:
        raise NotImplementedError

    def delete(self, user: User):
        raise NotImplementedError

    def delete_realm(self):
        raise NotImplementedError


class KeyCloakUserManger(BaseUserManager):
    def __init__(self, session: KeycloakAdmin):
        self.session = session

    def create(self, **kwargs) -> KeycloakUser:
        new_user_id = self.session.create_user(
            {
                "email": kwargs["username"],
                "username": kwargs["username"],
                "enabled": True,
                "firstName": "some",
                "lastName": "one",
                "credentials": [
                    {
                        "type": "password",
                        "value": kwargs["password"],
                        "temporary": False,
                    }
                ],
                "attributes": {
                    "is_admin": kwargs["is_admin"],
                    "requests_per_minute": kwargs.get("requests_per_minute", 60),
                    "tokens_per_minute": kwargs.get("tokens_per_minute", 100_000),
                    "cost_usd_per_month": kwargs.get("cost_usd_per_month", 10),
                },
            },
            exist_ok=True,
        )
        user = KeycloakUser(
            id=UUID(new_user_id),
            username=kwargs["username"],
            password=kwargs["password"],
            is_admin=kwargs["is_admin"],
            requests_per_minute=kwargs.get("requests_per_minute", 60),
            tokens_per_minute=kwargs.get("tokens_per_minute", 100_000),
            cost_usd_per_month=kwargs.get("cost_usd_per_month", 10),
        )
        return user

    def delete(self, user: KeycloakUser):
        pass

    def delete_realm(self):
        self.session.delete_realm(env.auth.realm_name)


class SQLUserManger(BaseUserManager):
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> SQLUser:
        user = SQLUser(
            id=kwargs.get("id", uuid4()),
            username=kwargs["username"],
            is_admin=kwargs["is_admin"],
            requests_per_minute=kwargs.get("requests_per_minute", 60),
            tokens_per_minute=kwargs.get("tokens_per_minute", 100_000),
            cost_usd_per_month=kwargs.get("cost_usd_per_month", 10),
            hashed_password=pwd_context.hash(kwargs["password"]),
        )

        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def delete(self, user: SQLUser):
        self.session.delete(user)
        self.session.commit()

    def delete_realm(self):
        pass


@pytest.fixture
def user_manager(session) -> BaseUserManager:
    if not isinstance(env.auth, KeycloakSettings):
        admin = SQLUserManger(session)
    else:
        keycloak_openid = KeycloakOpenID(
            server_url=env.auth.server_url,
            client_id=env.auth.client_id,
            realm_name="master",
            client_secret_key=env.auth.client_secret_key,
        )
        keycloak_connection = KeycloakOpenIDConnection(
            server_url=env.auth.server_url,
            username="admin",
            password="admin",
            realm_name=keycloak_openid.realm_name,
            client_secret_key=keycloak_openid.client_secret_key,
            verify=True,
        )
        admin = KeycloakAdmin(connection=keycloak_connection)

        new_realm = {
            "realm": env.auth.realm_name,
            "enabled": True,
        }
        admin.create_realm(new_realm, skip_exists=True)

        admin.connection.realm_name = env.auth.realm_name
        client_id = next(
            x["id"] for x in admin.get_clients() if x["clientId"] == "admin-cli"
        )

        for attr, type_ in (
            ("tokens_per_minute", "int"),
            ("requests_per_minute", "int"),
            ("cost_usd_per_month", "int"),
            ("is_admin", "bool"),
        ):
            mapper_config = {
                "name": f"{attr}-mapper",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-attribute-mapper",
                "consentRequired": False,
                "config": {
                    "user.attribute": attr,  # The attribute you want to map
                    "id.token.claim": "true",  # Include in ID token
                    "access.token.claim": "true",  # Include in Access token
                    "jsonType.label": type_,  # Type of the attribute
                    "claim.name": attr,
                },
            }
            try:
                admin.add_mapper_to_client(client_id, payload=mapper_config)
            except Exception:
                pass

        admin = KeyCloakUserManger(admin)

    yield admin
    admin.delete_realm()


@pytest.fixture
def real_name():
    return "my-test-realm"


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
def admin_user(session, admin_user_password, user_manager: BaseUserManager):
    user = user_manager.create(
        username="some.one@department.gov.uk",
        password=admin_user_password,
        is_admin=True,
        requests_per_minute=60,
        tokens_per_minute=100_000,
        cost_usd_per_month=10,
    )

    yield user

    user_manager.delete(user=user)


@pytest.fixture
def normal_user(user_manager, admin_user_password):
    user = user_manager.create(
        username="an.other@department.gov.uk",
        password=admin_user_password,
        is_admin=False,
        requests_per_minute=60,
        tokens_per_minute=1_000,
        cost_usd_per_month=10,
    )

    yield user

    user_manager.delete(user=user)


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


def get_headers(user: User) -> dict[str, str]:
    token = get_token(user)
    return {"Authorization": f"Bearer {token}"}
