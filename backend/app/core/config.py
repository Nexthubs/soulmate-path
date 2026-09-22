from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Soulmate Path API"
    app_version: str = "v1"
    environment: str = "development"
    debug: bool = False
    app_base_url: str = "http://localhost:3000"
    api_prefix: str = "/api/soulmate"

    # CORS configuration: strict list of allowed origins, never wildcard with credentials
    cors_allow_origins: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Database connection URL (defaults to local docker postgres for development)
    database_url: str = "postgresql://soulmate:soulmate_dev_password@localhost:5432/soulmate_dev"


settings = Settings()
