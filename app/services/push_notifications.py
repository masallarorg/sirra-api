from __future__ import annotations

import asyncio
from typing import Any


_NOTIFICATION_AUDIO: dict[str, tuple[str, str]] = {
    "general": ("fortune_general_voice_v5", "sirra_fortune_ready_voice"),
    "coffee": ("fortune_coffee_voice_v5", "sirra_coffee_ready_voice"),
    "tarot": ("fortune_tarot_voice_v5", "sirra_tarot_ready_voice"),
    "katina": ("fortune_tarot_voice_v5", "sirra_tarot_ready_voice"),
    "dream": ("fortune_dream_voice_v5", "sirra_dream_ready_voice"),
    "palm": ("fortune_palm_voice_v5", "sirra_palm_ready_voice"),
    "soulmate": ("fortune_soulmate_voice_v5", "sirra_soulmate_ready_voice"),
    "premium": ("premium_voice_v5", "sirra_premium_voice"),
    "admin": ("admin_voice_v2", "sirra_admin_voice"),
}


def _audio_profile(*, message_type: str, fortune_type: str | None) -> tuple[str, str]:
    if message_type == "admin_message":
        return _NOTIFICATION_AUDIO["admin"]
    if message_type in {"premium", "premium_nudge"}:
        return _NOTIFICATION_AUDIO["premium"]
    normalized = str(fortune_type or "").strip().lower()
    return _NOTIFICATION_AUDIO.get(normalized, _NOTIFICATION_AUDIO["general"])


def _send_sync(
    *,
    user_id: str,
    title: str,
    body: str,
    route: str,
    message_type: str = "fortune_ready",
    fortune_type: str | None = None,
) -> bool:
    import firebase_admin
    from firebase_admin import firestore, messaging

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    user = db.collection("users").document(user_id).get()
    data: dict[str, Any] = user.to_dict() if user.exists else {}
    tokens = [str(item).strip() for item in (data.get("fcm_tokens") or []) if str(item).strip()]
    if not tokens:
        return False
    channel_id, sound = _audio_profile(message_type=message_type, fortune_type=fortune_type)
    message = messaging.MulticastMessage(
        tokens=tokens[:500],
        notification=messaging.Notification(title=title, body=body),
        data={
            "route": route,
            "type": message_type,
            "fortune_type": str(fortune_type or "general"),
        },
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id=channel_id,
                sound=sound,
                default_vibrate_timings=True,
                visibility="public",
            ),
        ),
    )
    response = messaging.send_each_for_multicast(message)
    invalid: list[str] = []
    success = False
    for index, item in enumerate(response.responses):
        success = success or bool(item.success)
        if not item.success and index < len(tokens):
            code = getattr(item.exception, "code", "") if item.exception else ""
            if code in {"registration-token-not-registered", "invalid-argument"}:
                invalid.append(tokens[index])
    if invalid:
        db.collection("users").document(user_id).set(
            {"fcm_tokens": firestore.ArrayRemove(invalid)}, merge=True
        )
    return success


async def notify_fortune_ready(
    *,
    user_id: str,
    fortune_id: str,
    title: str,
    fortune_type: str = "general",
) -> None:
    try:
        await asyncio.to_thread(
            _send_sync,
            user_id=user_id,
            title=f"{title} hazır",
            body="Yorumun tamamlandı. Görmek için dokun.",
            route=f"/fortune/result/{fortune_id}",
            message_type="fortune_ready",
            fortune_type=fortune_type,
        )
    except Exception:
        # Bildirim hatası tamamlanmış falı başarısız saymamalı.
        return


async def notify_admin_message(*, user_id: str, title: str, body: str, route: str = "/") -> bool:
    try:
        return await asyncio.to_thread(
            _send_sync,
            user_id=user_id,
            title=title,
            body=body,
            route=route,
            message_type="admin_message",
            fortune_type=None,
        )
    except Exception:
        return False
