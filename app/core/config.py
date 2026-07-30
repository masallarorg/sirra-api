from functools import cached_property
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Sırra Backend"
    environment: str = "production"
    mock_ai: bool = False
    allow_mock_auth: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_api_base: str = "https://api.openai.com/v1"
    openai_reasoning_effort: str | None = "low"
    openai_max_output_tokens: int = 2600
    openai_request_timeout_seconds: float = 70.0
    openai_retries: int = 2
    google_tts_enabled: bool = True
    google_tts_language_code: str = 'tr-TR'
    google_tts_voice_name: str = 'tr-TR-Chirp3-HD-Aoede'
    speech_fallback_enabled: bool = True
    speech_model: str = 'gpt-4o-mini-tts'
    speech_voice: str = 'marin'
    firebase_credentials_path: str | None = None
    cors_origins: str = "*"
    cors_allow_credentials: bool = False
    rate_limit_per_minute: int = 18
    revenuecat_webhook_secret: str | None = None
    google_play_package_name: str = "com.sirrafal.app"
    google_play_service_account_json: str | None = None
    google_play_service_account_path: str | None = None
    trusted_hosts: str = "*"
    max_image_upload_mb: int = 8
    max_openai_image_edge_px: int = 1280
    admob_rewarded_ad_unit_id: str = "ca-app-pub-7479381661494073/9143635106"
    admob_reward_amount: int = 2
    admob_ssv_keys_url: str = "https://www.gstatic.com/admob/reward/verifier-keys.json"
    admob_ssv_max_age_seconds: int = 86400

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
