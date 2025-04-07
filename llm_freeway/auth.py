from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError, PyJWKClient
from starlette import status

from llm_freeway.database import User, env

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    try:
        jwks_client = PyJWKClient(
            f"{env.auth.server_url}/realms/{env.auth.realm_name}/protocol/openid-connect/certs"
        )
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=["RS256"])

        return User(
            id=payload["sub"],
            username=payload["preferred_username"],
            requests_per_minute=payload["requests_per_minute"],
            is_admin=payload["is_admin"],
            tokens_per_minute=payload["tokens_per_minute"],
            cost_usd_per_month=payload["cost_usd_per_month"],
        )
    except (InvalidTokenError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]):
    if current_user and not current_user.is_admin:
        raise HTTPException(
            status_code=httpx.codes.UNAUTHORIZED,
            detail="you need to be an admin to perform this action",
        )
    return current_user


def get_token_native(user: User) -> str:
    access_token_expires = timedelta(minutes=env.auth.access_token_expire_minutes)
    data = {"sub": user.username}
    expire = datetime.now(timezone.utc) + access_token_expires
    data.update({"exp": expire})
    encoded_jwt = jwt.encode(data, env.secret_key, algorithm=env.algorithm)
    return encoded_jwt


def get_token_keycloak(user: User) -> str:
    data = {
        "client_id": env.auth.client_id,
        "client_secret": env.auth.client_secret_key,
        "username": user.username,
        "password": user.password,
        "grant_type": "password",
    }

    keycloak_url = f"{env.auth.server_url}/realms/{env.auth.realm_name}/protocol/openid-connect/token"
    response = requests.post(keycloak_url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]
