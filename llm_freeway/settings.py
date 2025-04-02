from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://"
    public_key_url: str
    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")


load_dotenv()
env = Settings()
