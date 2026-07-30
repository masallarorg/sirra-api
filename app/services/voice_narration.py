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
    text = re.sub(r"[*_#>`~]+", "", text)
    text = re.sub(r"\b(?:ChatGPT|OpenAI|yapay zek[aâ])\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:3900]


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


async def _google_speech(text: str) -> tuple[bytes, str]:
    token, project_id = await asyncio.to_thread(_access_token)
    payload = {
        "input": {"text": text},
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
    return base64.b64decode(raw, validate=True), settings.google_tts_voice_name


async def _fallback_speech(text: str) -> tuple[bytes, str]:
    if not settings.speech_fallback_enabled or not settings.openai_api_key:
        raise RuntimeError("Speech fallback is not configured")
    url = f"{settings.openai_api_base.rstrip('/')}/audio/speech"
    payload = {
        "model": settings.speech_model,
        "voice": settings.speech_voice,
        "input": text,
        "instructions": "Sakin, sıcak, gizemli ve doğal Türkçe konuş. Marka veya teknoloji adı söyleme.",
        "response_format": "mp3",
    }
    async with httpx.AsyncClient(timeout=70.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        body = response.text[:500].replace(settings.openai_api_key or "", "[REDACTED]")
        raise RuntimeError(f"Speech API {response.status_code}: {body}")
    if not response.content:
        raise RuntimeError("Speech API returned empty audio")
    return response.content, settings.speech_voice


async def synthesize_fortune_narration(*, text: str, title: str) -> tuple[str, str]:
    clean = _clean_text(text)
    if len(clean) < 8:
        raise AppError(
            error_code="NARRATION_TEXT_EMPTY",
            user_message="Seslendirilecek fal metni bulunamadı.",
            developer_message="Narration input was empty after sanitization",
            status_code=422,
        )

    full_text = _clean_text(f"{title}. {clean}")
    errors: list[str] = []
    if settings.google_tts_enabled:
        try:
            audio, voice = await _google_speech(full_text)
            return base64.b64encode(audio).decode("ascii"), voice
        except Exception as exc:
            errors.append(str(exc))

    try:
        audio, voice = await _fallback_speech(full_text)
        return base64.b64encode(audio).decode("ascii"), voice
    except Exception as exc:
        errors.append(str(exc))

    raise AppError(
        error_code="NARRATION_UNAVAILABLE",
        user_message="Sesli yorum şu anda hazırlanamadı. Biraz sonra tekrar deneyebilirsin.",
        developer_message=" | ".join(errors)[-1600:],
        status_code=503,
        retryable=True,
    )
