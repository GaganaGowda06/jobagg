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
    gemini_api_key: SecretStr
    # Optional: enables the OpenRouter fallback when Gemini's daily quota
    # dies. Absent = fallback silently disabled, everything else works.
    openrouter_api_key: SecretStr | None = None
    # Optional: enables the email digest. Absent = digest silently skipped.
    gmail_address: str | None = None
    gmail_app_password: SecretStr | None = None


def get_settings() -> Settings:
    return Settings()
