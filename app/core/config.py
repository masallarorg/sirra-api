from functools import cached_property
from urllib.parse import unquote, urlparse


def _clean_env_secret(value: str | None, key_name: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"\"", "\'"}:
        text = text[1:-1].strip()
    prefix = f"{key_name}="
    if text.upper().startswith(prefix):
        text = text[len(prefix):].strip()
    return text

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Sırra Backend"
    environment: str = "production"
    mock_ai: bool = False
    allow_mock_auth: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6"
    openai_vision_model: str | None = None
    openai_image_model: str = "gpt-image-2"
    openai_api_base: str = "https://api.openai.com/v1"
    openai_reasoning_effort: str | None = "low"
    openai_max_output_tokens: int = 2600
    openai_request_timeout_seconds: float = 70.0
    openai_retries: int = 2
    google_tts_enabled: bool = True
    google_tts_language_code: str = "tr-TR"
    google_tts_voice_name: str = "tr-TR-Chirp3-HD-Aoede"
    speech_fallback_enabled: bool = True
    speech_model: str = "gpt-4o-mini-tts"
    speech_voice: str = "marin"
    firebase_credentials_path: str | None = None
    cors_origins: str = "*"
    cors_allow_credentials: bool = False
    rate_limit_per_minute: int = 18
    revenuecat_webhook_secret: str | None = None
    google_play_package_name: str = "com.sirrafal.app"
    google_play_service_account_json: str | None = None
    google_play_service_account_path: str | None = None
    trusted_hosts: str = "*"
    max_image_upload_mb: int = 16
    max_openai_image_edge_px: int = 1280
    admob_rewarded_ad_unit_id: str = "ca-app-pub-7479381661494073/9143635106"
    admob_reward_amount: int = 2
    admob_ssv_keys_url: str = "https://www.gstatic.com/admob/reward/verifier-keys.json"
    admob_ssv_max_age_seconds: int = 86400
    admin_emails: str = ""

    # Card-free media storage. Cloudinary's Free plan can be used without a
    # payment card, subject to the account's free usage quota.
    storage_provider: str = "cloudinary"
    cloudinary_enabled: bool = True
    cloudinary_url: str | None = None
    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: str | None = None
    cloudinary_api_secret: str | None = None
    cloudinary_folder_root: str = "sirra"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def vision_model(self) -> str:
        configured = str(self.openai_vision_model or "").strip()
        return configured or self.openai_model

    @cached_property
    def trusted_hosts_list(self) -> list[str]:
        if self.trusted_hosts.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @cached_property
    def admin_emails_list(self) -> set[str]:
        return {item.strip().lower() for item in self.admin_emails.split(",") if item.strip()}

    @property
    def cloudinary_credentials(self) -> tuple[str, str, str] | None:
        """Return (cloud_name, api_key, api_secret) from separate vars or URL.

        Cloudinary exposes a single CLOUDINARY_URL value in the form:
        cloudinary://API_KEY:API_SECRET@CLOUD_NAME
        Separate environment variables remain supported for easier rotation.
        """
        cloud_name = _clean_env_secret(self.cloudinary_cloud_name, "CLOUDINARY_CLOUD_NAME")
        api_key = _clean_env_secret(self.cloudinary_api_key, "CLOUDINARY_API_KEY")
        api_secret = _clean_env_secret(self.cloudinary_api_secret, "CLOUDINARY_API_SECRET")
        if cloud_name and api_key and api_secret:
            return cloud_name, api_key, api_secret

        raw_url = _clean_env_secret(self.cloudinary_url, "CLOUDINARY_URL")
        if not raw_url:
            return None
        parsed = urlparse(raw_url)
        if parsed.scheme.lower() != "cloudinary" or not parsed.hostname:
            return None
        parsed_key = unquote(parsed.username or "").strip()
        parsed_secret = unquote(parsed.password or "").strip()
        parsed_cloud = unquote(parsed.hostname or "").strip()
        if not (parsed_cloud and parsed_key and parsed_secret):
            return None
        return parsed_cloud, parsed_key, parsed_secret


    @property
    def cloudinary_credential_source(self) -> str:
        cloud_name = _clean_env_secret(self.cloudinary_cloud_name, "CLOUDINARY_CLOUD_NAME")
        api_key = _clean_env_secret(self.cloudinary_api_key, "CLOUDINARY_API_KEY")
        api_secret = _clean_env_secret(self.cloudinary_api_secret, "CLOUDINARY_API_SECRET")
        if cloud_name and api_key and api_secret:
            return "separate_environment_variables"
        if _clean_env_secret(self.cloudinary_url, "CLOUDINARY_URL"):
            return "cloudinary_url"
        return "missing"

    @property
    def cloudinary_configured(self) -> bool:
        return bool(self.cloudinary_enabled and self.cloudinary_credentials)

    @cached_property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
