from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import boto3
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


def get_session():
    with Session(engine) as session:
        yield session


class Spend(BaseModel):
    requests: int
    completion_tokens: int
    prompt_tokens: int
    cost_usd: float | None


class User(BaseModel):
    id: UUID
    username: str
    password: str | None = None
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


class LLM(BaseModel):
    name: str
    input_cost_per_token: float
    output_cost_per_token: float


class LLMConfig(BaseModel):
    models: list[LLM]


def get_models() -> LLMConfig:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=env.aws_access_key_id,
        aws_secret_access_key=env.aws_secret_access_key,
        region_name=env.aws_region_name,
        endpoint_url=env.minio_host,
    )
    obj = s3.get_object(Bucket=env.s3_bucket, Key=env.s3_key)["Body"]
    return LLMConfig.model_validate_json(obj.read())


class EventLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    response_id: str = Field(index=True)
    user_id: UUID = Field()
    model: str
    prompt_tokens: int = Field()
    completion_tokens: int = Field()
    cost_usd: float | None = None
