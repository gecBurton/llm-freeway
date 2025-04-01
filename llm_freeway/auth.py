from typing import Annotated

import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from starlette import status

from llm_freeway.database import User, env

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_public_key() -> tuple[str, str]:
    public_key_url = f"{env.keycloak_server_url}/realms/{env.keycloak_realm_name}/protocol/openid-connect/certs"

    # Get the public keys
    response = requests.get(public_key_url)
    jwks = response.json()

    # Extract the public key (you may need to adjust this for multiple keys)
    key = jwks["keys"][0]  # Assume the first key in the list for simplicity
    n = key["n"]
    e = key["e"]
    alg = key["alg"]

    # Construct the public key for verification
    return f"-----BEGIN PUBLIC KEY-----\n{n}\n{e}\n-----END PUBLIC KEY-----", alg


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    public_key_alg: Annotated[tuple[str, str], Depends(get_public_key)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    public_key, alg = public_key_alg
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        # payload = jwt.decode(token, public_key, algorithms=[alg])
    except InvalidTokenError:
        raise credentials_exception
    return User(
        id=payload.get("sub"),
        username=payload.get("preferred_username"),
        requests_per_minute=payload.get("requests_per_minute"),
        is_admin=payload.get("is_admin"),
        tokens_per_minute=payload.get("tokens_per_minute"),
        cost_usd_per_month=payload.get("cost_usd_per_month"),
    )
