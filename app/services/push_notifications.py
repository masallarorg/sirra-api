from __future__ import annotations

import asyncio
from typing import Any


def _send_sync(*, user_id: str, title: str, body: str, route: str) -> None:
    import firebase_admin
    from firebase_admin import firestore, messaging

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    user = db.collection("users").document(user_id).get()
    data: dict[str, Any] = user.to_dict() if user.exists else {}
    tokens = [str(item).strip() for item in (data.get("fcm_tokens") or []) if str(item).strip()]
    if not tokens:
        return
    message = messaging.MulticastMessage(
        tokens=tokens[:500],
        notification=messaging.Notification(title=title, body=body),
        data={"route": route, "type": "fortune_ready"},
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="fortune_ready_channel_v3",
                sound="sirra_whisper",
                default_vibrate_timings=True,
                visibility="public",
            ),
        ),
    )
    response = messaging.send_each_for_multicast(message)
    invalid: list[str] = []
    for index, item in enumerate(response.responses):
        if not item.success and index < len(tokens):
            code = getattr(item.exception, "code", "") if item.exception else ""
            if code in {"registration-token-not-registered", "invalid-argument"}:
                invalid.append(tokens[index])
    if invalid:
        db.collection("users").document(user_id).set(
            {"fcm_tokens": firestore.ArrayRemove(invalid)}, merge=True
        )


async def notify_fortune_ready(*, user_id: str, fortune_id: str, title: str) -> None:
    try:
        await asyncio.to_thread(
            _send_sync,
            user_id=user_id,
            title=f"{title} hazır",
            body="Yorumun tamamlandı. Görmek için dokun.",
            route=f"/fortune/result/{fortune_id}",
        )
    except Exception:
        # Bildirim hatası tamamlanmış falı başarısız saymamalı.
        return
