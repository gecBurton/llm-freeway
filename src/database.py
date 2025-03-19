from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlmodel import Field, Session, SQLModel, select

from src.settings import env

connect_args = {"check_same_thread": False}
engine = create_engine(env.sqlite_url, connect_args=connect_args)


class Token(BaseModel):
    access_token: str
    token_type: str


def create_access_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, env.secret_key, algorithm=env.algorithm)
    return encoded_jwt


def get_session():
    with Session(engine) as session:
        yield session


class Spend(BaseModel):
    requests: int | None = None
    completion_tokens: int | None = None
    prompt_tokens: int | None = None


class User(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(unique=True)
    is_admin: bool = False
    requests_per_minute: int = 60

    def get_token(self) -> Token:
        access_token_expires = timedelta(minutes=env.access_token_expire_minutes)
        access_token = create_access_token(
            data={"sub": self.username},
            expires_delta=access_token_expires,
        )
        return Token(access_token=access_token, token_type="bearer")

    def headers(self) -> dict[str, str]:
        token = self.get_token()
        return {"Authorization": f"Bearer {token.access_token}"}

    def get_spend(self, session) -> Spend:
        one_minute_ago = datetime.now(tz=UTC) - timedelta(minutes=1)

        events = session.exec(
            select(EventLog).where(
                EventLog.user_id == self.id, EventLog.timestamp <= one_minute_ago
            )
        ).all()
        completion_tokens_sum = sum(event.completion_tokens for event in events)
        prompt_tokens_sum = sum(event.prompt_tokens for event in events)
        requests = sum(1 for _ in events)

        return Spend(
            completion_tokens=completion_tokens_sum,
            prompt_tokens=prompt_tokens_sum,
            requests=requests,
        )


class UserDB(User, table=True):
    hashed_password: str


class EventLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    response_id: str = Field(index=True)
    user_id: UUID = Field(default=None, foreign_key="userdb.id")
    model: str = Field()
    prompt_tokens: int = Field()
    completion_tokens: int = Field()


def get_account(
    username: str, session: Annotated[Session, Depends(get_session)]
) -> UserDB:
    return session.exec(select(UserDB).where(UserDB.username == username)).first()
