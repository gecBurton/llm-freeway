import jwt
import requests

from llm_freeway.settings import Settings

env = Settings()

data = {
    "client_id": env.keycloak_client_id,
    "client_secret": env.client_secret_key,
    "username": "admin",
    "password": "admin",
    "grant_type": "password",
}

keycloak_url = f"{env.keycloak_server_url}/realms/{env.keycloak_realm_name}/protocol/openid-connect/token"

response = requests.post(keycloak_url, data=data)
response.raise_for_status()

print(
    list(
        jwt.decode(response.json()["access_token"], options={"verify_signature": False})
    )
)
