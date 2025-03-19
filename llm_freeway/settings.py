from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    sqlite_url: str = "sqlite:///database.db"
    secret_key: str = "insecure"
    algorithm: Literal[
        "HS265", "HS256", "ES256", "ES384", "ES512", "ES256K", "RS256", "HS256", "EdDSA"
    ] = "HS265"
    access_token_expire_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")


env = Settings()
