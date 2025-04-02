from datetime import datetime, timedelta

import pytest
import requests
from keycloak import KeycloakAdmin, KeycloakOpenID, KeycloakOpenIDConnection
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.database import LLM, EventLog, LLMConfig, User, get_models, get_session

keycloak_client_id = "admin-cli"
keycloak_client_secret_key = "secret"
keycloak_realm_name = "tmp-realm"
keycloak_server_url = "http://localhost:8080"


@pytest.fixture
def keycloak_openid() -> KeycloakOpenID:
    return KeycloakOpenID(
        server_url=keycloak_server_url,
        client_id=keycloak_client_id,
        realm_name="master",
        client_secret_key=keycloak_client_secret_key,
    )


@pytest.fixture
def keycloak_admin(keycloak_openid):
    keycloak_connection = KeycloakOpenIDConnection(
        server_url=keycloak_server_url,
        username="admin",
        password="admin",
        realm_name=keycloak_openid.realm_name,
        client_secret_key=keycloak_openid.client_secret_key,
        verify=True,
    )
    admin = KeycloakAdmin(connection=keycloak_connection)

    new_realm = {
        "realm": keycloak_realm_name,
        "enabled": True,
    }
    admin.create_realm(new_realm, skip_exists=True)

    admin.connection.realm_name = keycloak_realm_name
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

    yield admin
    admin.delete_realm(keycloak_realm_name)


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


@pytest.fixture()
def client(get_session_override, get_models_override):
    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_models] = get_models_override

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
def admin_user(admin_user_password, keycloak_admin):
    username = "some.one@department.gov.uk"
    new_user_id = keycloak_admin.create_user(
        {
            "email": username,
            "username": username,
            "enabled": True,
            "firstName": "some",
            "lastName": "one",
            "credentials": [
                {
                    "type": "password",
                    "value": admin_user_password,
                    "temporary": False,
                }
            ],
            "attributes": {
                "is_admin": True,
                "requests_per_minute": 60,
                "tokens_per_minute": 100_000,
                "cost_usd_per_month": 10,
            },
        },
        exist_ok=True,
    )

    user = User(
        id=new_user_id,
        username=username,
        password=admin_user_password,
        is_admin=True,
        requests_per_minute=60,
        tokens_per_minute=100_000,
        cost_usd_per_month=10,
    )

    yield user

    keycloak_admin.delete_user(user_id=new_user_id)


@pytest.fixture
def normal_user(keycloak_admin, admin_user_password):
    username = "an.other@department.gov.uk"
    new_user_id = keycloak_admin.create_user(
        {
            "email": username,
            "username": username,
            "enabled": True,
            "firstName": "an",
            "lastName": "other",
            "credentials": [
                {
                    "type": "password",
                    "value": admin_user_password,
                    "temporary": False,
                }
            ],
            "attributes": {
                "is_admin": False,
                "requests_per_minute": 60,
                "tokens_per_minute": 1_000,
                "cost_usd_per_month": 10,
            },
        },
        exist_ok=True,
    )

    user = User(
        id=new_user_id,
        username="an.other@department.gov.uk",
        password=admin_user_password,
        is_admin=False,
        requests_per_minute=60,
        tokens_per_minute=1_000,
        cost_usd_per_month=10,
    )

    yield user
    keycloak_admin.delete_user(user_id=new_user_id)


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


def get_token(user: User) -> str:
    data = {
        "client_id": keycloak_client_id,
        "client_secret": keycloak_client_secret_key,
        "username": user.username,
        "password": user.password,
        "grant_type": "password",
    }

    keycloak_url = f"{keycloak_server_url}/realms/{keycloak_realm_name}/protocol/openid-connect/token"
    response = requests.post(keycloak_url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


def get_headers(user: User) -> dict[str, str]:
    token = get_token(user)
    return {"Authorization": f"Bearer {token}"}
