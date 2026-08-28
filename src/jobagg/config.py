"""Application configuration, loaded from environment variables / .env.

All secrets are typed as SecretStr so they never appear in plaintext if a
Settings object is logged, printed, or repr()'d by accident.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adzuna_app_id: SecretStr
    adzuna_app_key: SecretStr
    reed_api_key: SecretStr


def get_settings() -> Settings:
    return Settings()
