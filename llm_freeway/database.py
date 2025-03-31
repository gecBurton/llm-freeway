from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import requests
from fastapi import Depends
from keycloak import KeycloakAdmin, KeycloakOpenID, KeycloakOpenIDConnection
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


def get_keycloak_admin() -> KeycloakAdmin:
    keycloak_openid = KeycloakOpenID(
        server_url=env.keycloak_server_url,
        client_id="example_client",
        realm_name=env.keycloak_realm_name,
        client_secret_key=env.client_secret_key,
    )

    keycloak_connection = KeycloakOpenIDConnection(
        server_url=env.keycloak_server_url,
        username="admin",
        password="admin",
        realm_name=keycloak_openid.realm_name,
        client_secret_key=keycloak_openid.client_secret_key,
        verify=True,
    )

    return KeycloakAdmin(connection=keycloak_connection)


class Spend(BaseModel):
    requests: int
    completion_tokens: int
    prompt_tokens: int
    cost_usd: float | None


class User(BaseModel):
    id: UUID | None = Field()
    username: str = Field()
    password: str = Field()
    is_admin: bool = False
    requests_per_minute: int = 60
    tokens_per_minute: int = 100_000
    cost_usd_per_month: int = 10

    def get_token(self) -> str:
        data = {
            "client_id": env.keycloak_client_id,
            "client_secret": env.client_secret_key,
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        }
        keycloak_url = f"{env.keycloak_server_url}/realms/{env.keycloak_realm_name}/protocol/openid-connect/token"
        response = requests.post(keycloak_url, data=data)
        response.raise_for_status()
        return response.json()["access_token"]

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


def get_user(
    username: str, session: Annotated[KeycloakAdmin, Depends(get_keycloak_admin)]
) -> User:
    return User(username=username)
