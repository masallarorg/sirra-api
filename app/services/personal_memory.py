from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings


def _firestore_client_or_none():
    if settings.mock_ai or settings.allow_mock_auth:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
            else:
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception:
        return None


async def enrich_profile_with_memory(*, user_id: str, profile: dict[str, Any], focus: str | None = None) -> dict[str, Any]:
    """Attach a small, safe fortune memory summary to the model input.

    The memory never blocks fortune generation. It only uses the authenticated
    user's previous fortune documents and stores broad entertainment signals:
    symbols, types, focus labels and short summaries.
    """
    clean_profile = dict(profile or {})
    db = _firestore_client_or_none()
    if db is None:
        clean_profile.setdefault("personal_memory", _empty_memory(focus))
        return clean_profile

    try:
        docs = (
            db.collection("users")
            .document(user_id)
            .collection("fortunes")
            .order_by("created_at", direction="DESCENDING")
            .limit(12)
            .stream()
        )
        symbol_counter: Counter[str] = Counter()
        type_counter: Counter[str] = Counter()
        recent: list[dict[str, Any]] = []
        for doc in docs:
            item = doc.to_dict() or {}
            type_id = str(item.get("type") or "fortune")
            type_counter[type_id] += 1
            symbols = [str(s).strip() for s in (item.get("symbols") or []) if str(s).strip()]
            symbol_counter.update(symbols[:8])
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            profile_snapshot = item.get("profile_snapshot") if isinstance(item.get("profile_snapshot"), dict) else {}
            summary = str((payload or {}).get("summary") or item.get("summary") or "").strip()
            recent.append(
                {
                    "fortune_id": str(item.get("fortune_id") or doc.id),
                    "type": type_id,
                    "focus": str(item.get("focus") or profile_snapshot.get("focus") or "Genel enerji"),
                    "symbols": symbols[:6],
                    "summary": summary[:240],
                }
            )
        clean_profile["personal_memory"] = {
            "enabled": True,
            "current_focus": focus or clean_profile.get("focus") or "Genel enerji",
            "recent_count": len(recent),
            "top_symbols": [s for s, _ in symbol_counter.most_common(6)],
            "top_types": [t for t, _ in type_counter.most_common(4)],
            "recent_fortunes": recent[:5],
            "instruction": "Kullanıcının geçmiş sembollerini güvenli kişiselleştirme için kullan; kesin kader veya takip iddiası kurma.",
        }
    except Exception:
        clean_profile.setdefault("personal_memory", _empty_memory(focus))
    return clean_profile


def _empty_memory(focus: str | None) -> dict[str, Any]:
    return {
        "enabled": False,
        "current_focus": focus or "Genel enerji",
        "recent_count": 0,
        "top_symbols": [],
        "top_types": [],
        "recent_fortunes": [],
    }


async def store_fortune_memory(
    *,
    user_id: str,
    fortune_id: str,
    fortune_type: str,
    symbols: list[str],
    summary: str,
    focus: str | None = None,
) -> None:
    db = _firestore_client_or_none()
    if db is None:
        return
    try:
        now = datetime.now(UTC)
        clean_symbols = [str(s).strip() for s in symbols if str(s).strip()][:12]
        stats_ref = db.collection("users").document(user_id).collection("private_state").document("fortune_memory")
        snap = stats_ref.get()
        data = snap.to_dict() if snap.exists else {}
        counts = dict(data.get("symbol_counts") or {})
        for symbol in clean_symbols:
            counts[symbol] = int(counts.get(symbol) or 0) + 1
        stats_ref.set(
            {
                "last_fortune_id": fortune_id,
                "last_type": fortune_type,
                "last_focus": focus or "Genel enerji",
                "last_symbols": clean_symbols,
                "last_summary": summary[:400],
                "symbol_counts": counts,
                "updated_at": now,
            },
            merge=True,
        )
    except Exception:
        return
