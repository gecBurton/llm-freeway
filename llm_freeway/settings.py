from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "insecure"
    algorithm: Literal[
        "HS265", "HS256", "ES256", "ES384", "ES512", "ES256K", "RS256", "HS256", "EdDSA"
    ] = "HS265"
    access_token_expire_minutes: int = 30
    temp_admin_password: str | None = Field(
        default=None,
        description="if not none, an admin user will be created with username = 'admin' this password",
    )

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")


env = Settings()
