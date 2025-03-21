from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlmodel import Session
from starlette import status

from llm_freeway.database import User, env, get_account, get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def authenticate_user(
    username: str, password: str, session: Annotated[Session, Depends(get_session)]
) -> User | None:
    user = get_account(username, session)
    if not user:
        return None
    if not pwd_context.verify(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, env.secret_key, algorithms=[env.algorithm])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception
    user = get_account(username=username, session=session)
    if user is None:
        raise credentials_exception
    return user


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]):
    if current_user and not current_user.is_admin:
        raise HTTPException(
            status_code=httpx.codes.UNAUTHORIZED,
            detail="you need to be an admin to perform this action",
        )
    return current_user
