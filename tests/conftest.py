from datetime import datetime, timedelta

import pytest
from keycloak import KeycloakAdmin, KeycloakOpenID, KeycloakOpenIDConnection
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel
from starlette.testclient import TestClient

from llm_freeway.api import app
from llm_freeway.database import LLM, EventLog, User, get_session
from llm_freeway.settings import Settings


@pytest.fixture
def client_id():
    return env.keycloak_client_id


@pytest.fixture
def keycloak_openid(client_id) -> KeycloakOpenID:
    return KeycloakOpenID(
        server_url=env.keycloak_server_url,
        client_id=client_id,
        realm_name=env.keycloak_realm_name,
        client_secret_key=env.client_secret_key,
    )


@pytest.fixture
def keycloak_admin(keycloak_openid, client_id):
    keycloak_connection = KeycloakOpenIDConnection(
        server_url=env.keycloak_server_url,
        username="admin",
        password="admin",
        realm_name=keycloak_openid.realm_name,
        client_secret_key=keycloak_openid.client_secret_key,
        verify=True,
    )
    admin = KeycloakAdmin(connection=keycloak_connection)

    # Fetch the client ID
    client = admin.get_client_id(client_id)
    attributes = {
        "sub": {
            "type": "string",
            "id.token.claim": "true",
            "access.token.claim": "true",
        },
        "is_admin": {
            "type": "boolean",
            "id.token.claim": "true",
            "access.token.claim": "true",
        },
        "requests_per_minute": {
            "type": "integer",
            "id.token.claim": "true",
            "access.token.claim": "true",
        },
        "tokens_per_minute": {
            "type": "integer",
            "id.token.claim": "true",
            "access.token.claim": "true",
        },
        "cost_usd_per_month": {
            "type": "integer",
            "id.token.claim": "true",
            "access.token.claim": "true",
        },
    }

    existing_mappers = admin.get_mappers_from_client(client_id=client)
    for mapper in existing_mappers:
        admin.remove_client_mapper(client_id=client, client_mapper_id=mapper["id"])

    for attr, config in attributes.items():
        mapper = {
            "name": f"{attr} Mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "consentRequired": False,
            "config": {
                "user.property": attr,
                "id.token.claim": config["id.token.claim"],
                "access.token.claim": config["access.token.claim"],
                "claim.name": attr,
                "jsonType.label": config["type"],
            },
        }
        # Create the mapper
        admin.add_mapper_to_client(client_id=client, payload=mapper)

    # {
    #     "protocolMapper": "oidc-usermodel-property-mapper",
    #     "config": {
    #         "user.attribute": "username",
    #         "id.token.claim": "true",
    #     }
    # }
    return admin


env = Settings()


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
def admin_user(
    session, admin_user_password, keycloak_admin, keycloak_openid, client_id
):
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
def normal_user(session, keycloak_admin, admin_user_password, keycloak_openid):
    username = "an.other@department.gov.uk"
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
