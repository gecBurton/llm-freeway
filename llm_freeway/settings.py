from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeycloakSettings(BaseSettings):
    client_id: str
    client_secret_key: str
    realm_name: str
    server_url: str


class LocalAuthSettings(BaseSettings):
    access_token_expire_minutes: int = 15
    secret_key: str
    algorithm: str = "HS256"


class Settings(BaseSettings):
    database_url: str = "sqlite://"

    auth: KeycloakSettings | LocalAuthSettings

    model_config = SettingsConfigDict(
        env_file=".env", frozen=True, extra="allow", env_nested_delimiter="__"
    )


load_dotenv()
env = Settings()
