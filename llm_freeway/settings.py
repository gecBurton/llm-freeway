from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://"
    public_key_url: str

    minio_host: str | None = None
    s3_bucket: str = "llm-freeway"
    s3_key: str = "config.json"
    aws_region_name: str | None = None
    aws_access_key_id: str = "minio_access_key"
    aws_secret_access_key: str = "minio_secret_key"

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="allow")


load_dotenv()
env = Settings()
