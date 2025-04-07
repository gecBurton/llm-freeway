from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://"

    keycloak_client_id: str | None = None
    keycloak_client_secret_key: str | None = None
    keycloak_realm_name: str | None = None
    keycloak_server_url: str | None = None

    access_token_expire_minutes: int = 15
    secret_key: str | None
    algorithm: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")

    def get_token_url(self):
        return f"{self.keycloak_server_url}/realms/{self.keycloak_realm_name}/protocol/openid-connect/token"

    def get_certs_url(self):
        return f"{self.keycloak_server_url}/realms/{self.keycloak_realm_name}/protocol/openid-connect/certs"


load_dotenv()
env = Settings()
