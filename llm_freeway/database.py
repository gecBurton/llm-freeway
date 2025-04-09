from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import create_engine, func
from sqlmodel import Field, Session, SQLModel, select

from llm_freeway.settings import env

if env.database_url.startswith("sqlite://"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(env.database_url, connect_args=connect_args)
else:
    engine = create_engine(env.database_url)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Token(BaseModel):
    access_token: str
    token_type: str


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
    username: str
    is_admin: bool = False
    requests_per_minute: int = 60
    tokens_per_minute: int = 100_000
    cost_usd_per_month: int = 10

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


class SQLUser(User, table=True):
    hashed_password: str


class KeycloakUser(User):
    password: str


class LLMBase(SQLModel):
    input_cost_per_token: float
    output_cost_per_token: float


class LLM(LLMBase, table=True):
    name: str = Field(primary_key=True, description="the litellm-model name")


class EventLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    response_id: str = Field(index=True)
    user_id: UUID = Field()
    model: str = Field(foreign_key="llm.name")
    prompt_tokens: int = Field()
    completion_tokens: int = Field()
    cost_usd: float | None = None


def authenticate_user(
    username: str, password: str, session: Annotated[Session, Depends(get_session)]
) -> User | None:
    user = session.exec(select(SQLUser).where(SQLUser.username == username)).one()
    if not user:
        return None
    if not pwd_context.verify(password, user.hashed_password):
        return None
    return user
