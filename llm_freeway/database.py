from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, func
from sqlmodel import Field, Session, SQLModel, select

from llm_freeway.settings import env

if env.database_url.startswith("sqlite://"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(env.database_url, connect_args=connect_args)
else:
    engine = create_engine(env.database_url)


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
    requests: int
    completion_tokens: int
    prompt_tokens: int
    cost_usd: float | None


class User(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(unique=True)
    is_admin: bool = False
    requests_per_minute: int = 60
    tokens_per_minute: int = 100_000
    cost_usd_per_month: int = 10

    def get_token(self) -> str:
        access_token_expires = timedelta(minutes=env.access_token_expire_minutes)
        return create_access_token(
            data={"sub": self.username},
            expires_delta=access_token_expires,
        )

    def headers(self) -> dict[str, str]:
        token = self.get_token()
        return {"Authorization": f"Bearer {token}"}

    def get_spend(self, session) -> Spend:
        one_minute_ago = datetime.now(tz=UTC) - timedelta(minutes=1)
        one_month_ago = datetime.now(tz=UTC) - timedelta(days=30)

        completion_tokens, prompt_tokens, requests = session.exec(
            select(
                func.sum(EventLog.completion_tokens),
                func.sum(EventLog.prompt_tokens),
                func.count(EventLog.id),
            ).where(
                EventLog.user_id == self.id,
                EventLog.timestamp > one_minute_ago,
            )
        ).one()

        cost_usd = session.exec(
            select(
                func.sum(EventLog.cost_usd),
            ).where(
                EventLog.user_id == self.id,
                EventLog.timestamp > one_month_ago,
            )
        ).one()

        return Spend(
            completion_tokens=completion_tokens or 0,
            prompt_tokens=prompt_tokens or 0,
            requests=requests or 0,
            cost_usd=cost_usd,
        )


class UserDB(User, table=True):
    hashed_password: str


class LLMBase(SQLModel):
    input_cost_per_token: float
    output_cost_per_token: float


class LLM(LLMBase, table=True):
    name: str = Field(primary_key=True, description="the litellm-model name")


class EventLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    response_id: str = Field(index=True)
    user_id: UUID = Field(foreign_key="userdb.id")
    model: str = Field(foreign_key="llm.name")
    prompt_tokens: int = Field()
    completion_tokens: int = Field()
    cost_usd: float | None = None


def get_user(
    username: str, session: Annotated[Session, Depends(get_session)]
) -> UserDB:
    return session.exec(select(UserDB).where(UserDB.username == username)).first()
