import asyncio
import base64
import re

import httpx
from app.core.config import settings
from app.core.errors import AppError


_TTS_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    # Bildirim/ses katmanına markdown işaretlerini taşımıyoruz.
    text = re.sub(r"[*_#>`~]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:6000]


def _access_token() -> tuple[str, str | None]:
    from google.auth import default as google_auth_default
    from google.auth.transport.requests import Request as GoogleAuthRequest

    credentials, project_id = google_auth_default(scopes=[_TTS_SCOPE])
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())
    token = credentials.token
    if not token:
        raise RuntimeError("Google Cloud access token could not be created")
    return token, project_id


async def synthesize_fortune_narration(*, text: str, title: str) -> tuple[str, str]:
    clean = _clean_text(text)
    if len(clean) < 8:
        raise AppError(
            error_code="NARRATION_TEXT_EMPTY",
            user_message="Seslendirilecek fal metni bulunamadı.",
            developer_message="Narration input was empty after sanitization",
            status_code=422,
        )

    if not settings.google_tts_enabled:
        raise AppError(
            error_code="GOOGLE_TTS_DISABLED",
            user_message="Doğal sesli anlatım şu anda etkin değil.",
            developer_message="GOOGLE_TTS_ENABLED is false",
            status_code=503,
            retryable=True,
        )

    try:
        token, project_id = await asyncio.to_thread(_access_token)
        payload = {
            "input": {"text": f"{title}. {clean}"},
            "voice": {
                "languageCode": settings.google_tts_language_code,
                "name": settings.google_tts_voice_name,
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "effectsProfileId": ["handset-class-device"],
            },
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                _TTS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    **({"x-goog-user-project": project_id} if project_id else {}),
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Google TTS {response.status_code}: {response.text[:500]}")
        raw = response.json().get("audioContent")
        if not isinstance(raw, str) or not raw:
            raise RuntimeError("Google TTS response has no audioContent")
        # Geçersiz base64'ü kullanıcıya göndermeden doğrula.
        base64.b64decode(raw, validate=True)
        return raw, settings.google_tts_voice_name
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            error_code="NARRATION_UNAVAILABLE",
            user_message="Sesli yorum hazırlanamadı. Biraz sonra tekrar deneyebilirsin.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc
