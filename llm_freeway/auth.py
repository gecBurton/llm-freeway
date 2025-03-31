from typing import Annotated

import httpx
import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlmodel import Session
from starlette import status

from llm_freeway.database import User, env, get_session, get_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def authenticate_user(
    username: str, password: str, session: Annotated[Session, Depends(get_session)]
) -> User | None:
    user = get_user(username, session)
    if not user:
        return None
    if not pwd_context.verify(password, user.hashed_password):
        return None
    return user


def get_public_key():
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
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    public_key, alg = get_public_key()
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        # payload = jwt.decode(token, public_key, algorithms=[alg])
    except InvalidTokenError:
        raise credentials_exception
    if username := payload.get("sub"):
        return User(username=username)
    raise credentials_exception


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]):
    if current_user and not current_user.is_admin:
        raise HTTPException(
            status_code=httpx.codes.UNAUTHORIZED,
            detail="you need to be an admin to perform this action",
        )
    return current_user
