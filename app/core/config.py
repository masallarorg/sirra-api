from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fal AI Backend"
    environment: str = "production"
    mock_ai: bool = False
    allow_mock_auth: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    openai_api_base: str = "https://api.openai.com/v1"
    openai_reasoning_effort: str | None = "low"
    openai_max_output_tokens: int = 2600
    openai_request_timeout_seconds: float = 70.0
    openai_retries: int = 2
    firebase_credentials_path: str | None = None
    cors_origins: str = "*"
    cors_allow_credentials: bool = False
    rate_limit_per_minute: int = 18
    revenuecat_webhook_secret: str | None = None
    google_play_package_name: str = "com.sirrafal.app"
    google_play_service_account_json: str | None = None
    google_play_service_account_path: str | None = None
    allow_client_credit_sync: bool = False
    trusted_hosts: str = "*"
    max_image_upload_mb: int = 8
    max_openai_image_edge_px: int = 1280

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
