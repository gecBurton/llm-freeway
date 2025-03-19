from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlmodel import Session
from starlette import status

from llm_freeway.database import User, UserDB, env, get_account, get_session

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


def create_user_db(
    username,
    password,
    is_admin,
    tokens_per_minute,
    session: Annotated[Session, Depends(get_session)],
) -> UserDB | None:
    if get_account(username, session):
        return None

    user_db = UserDB(
        username=username,
        is_admin=is_admin,
        hashed_password=pwd_context.hash(password),
        tokens_per_minute=tokens_per_minute,
    )

    session.add(user_db)
    session.commit()
    session.refresh(user_db)
    return user_db
