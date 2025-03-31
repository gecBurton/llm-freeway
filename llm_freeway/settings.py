from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://"
    access_token_expire_minutes: int = 30
    temp_admin_password: str | None = Field(
        default=None,
        description="if not none, an admin user will be created with username = 'admin' this password",
    )
    keycloak_client_id: str = "admin-cli"
    client_secret_key: str = "secret"
    keycloak_server_url: str = "http://localhost:8080"
    keycloak_realm_name: str = "master"

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")


env = Settings()
