from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fal AI Backend"
    environment: str = "production"
    mock_ai: bool = False
    allow_mock_auth: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.2"
    firebase_credentials_path: str | None = None
    cors_origins: str = "*"
    rate_limit_per_minute: int = 18
    revenuecat_webhook_secret: str | None = None
    allow_client_credit_sync: bool = False
    trusted_hosts: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @cached_property
    def trusted_hosts_list(self) -> list[str]:
        if self.trusted_hosts.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @cached_property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
