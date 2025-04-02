from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError, PyJWKClient
from starlette import status

from llm_freeway.database import User, env

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    try:
        jwks_client = PyJWKClient(env.public_key_url)
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
