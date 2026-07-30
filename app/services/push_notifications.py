from __future__ import annotations

import asyncio
from typing import Any


def _send_sync(*, user_id: str, title: str, body: str, route: str, message_type: str = "fortune_ready") -> bool:
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
    channel_id = "admin_message_channel_v1" if message_type == "admin_message" else "fortune_ready_channel_v3"
    sound = "sirra_premium_chime" if message_type == "admin_message" else "sirra_whisper"
    message = messaging.MulticastMessage(
        tokens=tokens[:500],
        notification=messaging.Notification(title=title, body=body),
        data={"route": route, "type": message_type},
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


async def notify_fortune_ready(*, user_id: str, fortune_id: str, title: str) -> None:
    try:
        await asyncio.to_thread(
            _send_sync,
            user_id=user_id,
            title=f"{title} hazır",
            body="Yorumun tamamlandı. Görmek için dokun.",
            route=f"/fortune/result/{fortune_id}",
            message_type="fortune_ready",
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
        )
    except Exception:
        return False
