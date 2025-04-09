from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import httpx
import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError, PyJWKClient
from sqlalchemy.exc import NoResultFound
from sqlmodel import Session
from starlette import status

from llm_freeway.database import SQLUser, User, env, get_session
from llm_freeway.settings import KeycloakSettings, LocalAuthSettings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


NOT_AUTHORIZED_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _get_current_user(token: str, session: Session) -> dict:
    if isinstance(env.auth, KeycloakSettings):
        jwks_client = PyJWKClient(
            f"{env.auth.server_url}/realms/{env.auth.realm_name}/protocol/openid-connect/certs"
        )
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=["RS256"])
        payload["username"] = payload.pop("preferred_username")
        return payload

    if isinstance(env.auth, LocalAuthSettings):
        payload = jwt.decode(
            token, env.auth.secret_key, algorithms=[env.auth.algorithm]
        )
        session.get_one(SQLUser, UUID(payload["sub"]))
        return payload

    raise NOT_AUTHORIZED_ERROR


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    try:
        payload = _get_current_user(token, session)
        return User(
            id=payload["sub"],
            username=payload["username"],
            requests_per_minute=payload["requests_per_minute"],
            is_admin=payload["is_admin"],
            tokens_per_minute=payload["tokens_per_minute"],
            cost_usd_per_month=payload["cost_usd_per_month"],
        )

    except (InvalidTokenError, KeyError, NoResultFound):
        raise NOT_AUTHORIZED_ERROR


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]):
    if current_user and not current_user.is_admin:
        raise HTTPException(
            status_code=httpx.codes.UNAUTHORIZED,
            detail="you need to be an admin to perform this action",
        )
    return current_user


def get_token(user: User) -> str:
    if isinstance(env.auth, KeycloakSettings):
        data = {
            "client_id": env.auth.client_id,
            "client_secret": env.auth.client_secret_key,
            "username": user.username,
            "password": user.password,
            "grant_type": "password",
        }

        keycloak_url = f"{env.auth.server_url}/realms/{env.auth.realm_name}/protocol/openid-connect/token"
        response = requests.post(keycloak_url, data=data)
        if response.status_code != 200:
            raise NOT_AUTHORIZED_ERROR
        return response.json()["access_token"]

    if isinstance(env.auth, LocalAuthSettings):
        access_token_expires = timedelta(minutes=env.auth.access_token_expire_minutes)
        data = {
            "sub": str(user.id),
            "username": user.username,
            "requests_per_minute": user.requests_per_minute,
            "is_admin": user.is_admin,
            "tokens_per_minute": user.tokens_per_minute,
            "cost_usd_per_month": user.cost_usd_per_month,
            "exp": datetime.now(timezone.utc) + access_token_expires,
        }
        encoded_jwt = jwt.encode(
            data, env.auth.secret_key, algorithm=env.auth.algorithm
        )
        return encoded_jwt

    raise NotImplementedError
