import pytest
import requests
from keycloak import KeycloakAdmin, KeycloakOpenID, KeycloakOpenIDConnection

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


@pytest.fixture
def admin_user(keycloak_admin):
    admin_user_password = "admin"
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

    user = dict(
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


def get_token(user: dict) -> str:
    data = {
        "client_id": keycloak_client_id,
        "client_secret": keycloak_client_secret_key,
        "username": user["username"],
        "password": user["password"],
        "grant_type": "password",
    }

    keycloak_url = f"{keycloak_server_url}/realms/{keycloak_realm_name}/protocol/openid-connect/token"
    response = requests.post(keycloak_url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


def get_headers(user: dict) -> dict[str, str]:
    token = get_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_chat_completion(admin_user):
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello :)"}],
        "mock_response": "hello, how can i help you?",
    }
    response = requests.post(
        "http://localhost:8000/chat/completions",
        json=dict(payload, stream=False),
        headers=get_headers(admin_user),
    )
    assert response.status_code == 200, response.content
    assert (
        response.json()["choices"][0]["message"]["content"]
        == "hello, how can i help you?"
    )


def test_chat_completions_not_authenticated():
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello :)"}],
        "mock_response": "hello, how can i help you?",
    }
    response = requests.post(
        "http://localhost:8000/chat/completions",
        json=dict(payload, stream=False),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
