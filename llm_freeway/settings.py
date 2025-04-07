from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeycloakSettings(BaseSettings):
    client_id: str
    client_secret_key: str
    realm_name: str
    server_url: str


class Settings(BaseSettings):
    database_url: str = "sqlite://"

    keycloak: KeycloakSettings | None = None

    access_token_expire_minutes: int = 15
    secret_key: str | None
    algorithm: str = "HS256"

    model_config = SettingsConfigDict(
        env_file=".env", frozen=True, extra="allow", env_nested_delimiter="__"
    )

    def get_token_url(self):
        return f"{self.keycloak.server_url}/realms/{self.keycloak.realm_name}/protocol/openid-connect/token"

    def get_certs_url(self):
        return f"{self.keycloak.server_url}/realms/{self.keycloak.realm_name}/protocol/openid-connect/certs"


load_dotenv()
env = Settings()
