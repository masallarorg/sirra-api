from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
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


_SYMBOL_LABELS = {
    "dag": "Dağ",
    "yol": "Yol",
    "kus": "Kuş",
    "kalp": "Kalp",
    "anahtar": "Anahtar",
    "kapi": "Kapı",
    "kapı": "Kapı",
    "yuzuk": "Yüzük",
    "yüzük": "Yüzük",
    "balik": "Balık",
    "balık": "Balık",
    "goz": "Göz",
    "göz": "Göz",
    "ay": "Ay",
    "gunes": "Güneş",
    "güneş": "Güneş",
    "yilan": "Yılan",
    "yılan": "Yılan",
    "mektup": "Mektup",
    "telefon": "Telefon",
    "merdiven": "Merdiven",
    "deniz": "Deniz",
    "tren": "Tren",
    "ucak": "Uçak",
    "uçak": "Uçak",
    "tatil": "Tatil",
    "para": "Para",
    "is": "İş",
    "iş": "İş",
}

_THEME_GROUPS = {
    "ask": {
        "title": "Aşk ve bağ kurma",
        "symbols": {"kalp", "yuzuk", "yüzük", "iki_kisi", "cicek", "çiçek", "ay"},
        "keywords": {"ask", "aşk", "iliski", "ilişki", "sevgi", "barisma", "barışma", "eski"},
    },
    "haber": {
        "title": "Haber ve beklenen cevap",
        "symbols": {"kus", "kuş", "mektup", "telefon", "anahtar", "kapı", "kapi"},
        "keywords": {"haber", "mesaj", "cevap", "konusma", "konuşma", "iletişim", "iletisim"},
    },
    "yol": {
        "title": "Yol, değişim ve yer hareketi",
        "symbols": {"yol", "kapi", "kapı", "anahtar", "deniz", "tren", "ucak", "uçak", "merdiven"},
        "keywords": {"yol", "seyahat", "tatil", "tasınma", "taşınma", "degisim", "değişim", "karar"},
    },
    "kariyer": {
        "title": "Kariyer ve görünür olma",
        "symbols": {"dag", "dağ", "merdiven", "gunes", "güneş", "anahtar", "para"},
        "keywords": {"kariyer", "is", "iş", "para", "teklif", "proje", "okul"},
    },
    "koruma": {
        "title": "Koruma, sezgi ve kapalı konu",
        "symbols": {"goz", "göz", "yilan", "yılan", "golge", "gölge", "ay", "kapali_kapi"},
        "keywords": {"gizli", "kıskanç", "kiskanclik", "koruma", "sezgi", "belirsiz"},
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _label(symbol: str) -> str:
    clean = _normalize(symbol)
    return _SYMBOL_LABELS.get(clean, clean.replace("_", " ").title() if clean else "Sembol")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    text = str(value).strip()
    return text or None


def _extract_symbols(item: dict[str, Any]) -> list[str]:
    raw_symbols = item.get("symbols") or []
    if raw_symbols:
        return [_normalize(s) for s in raw_symbols if _normalize(s)][:10]
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    detected = payload.get("detected_symbols") or []
    symbols: list[str] = []
    if isinstance(detected, list):
        for entry in detected:
            if isinstance(entry, dict):
                clean = _normalize(entry.get("symbol") or entry.get("display_name"))
                if clean:
                    symbols.append(clean)
    api_symbols = payload.get("api_symbols") or []
    if isinstance(api_symbols, list):
        symbols.extend(_normalize(s) for s in api_symbols if _normalize(s))
    return symbols[:10]


def _extract_focus(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    snapshot = item.get("profile_snapshot") if isinstance(item.get("profile_snapshot"), dict) else {}
    focus = item.get("focus") or payload.get("focus") or snapshot.get("focus") or snapshot.get("main_interest") or "Genel enerji"
    return str(focus).strip() or "Genel enerji"


def _theme_scores(symbols: Counter[str], focuses: Counter[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    focus_texts = [(key.lower(), count) for key, count in focuses.items()]
    for theme, spec in _THEME_GROUPS.items():
        score = 0
        for symbol, count in symbols.items():
            if symbol in spec["symbols"]:
                score += 18 * count
        for focus, count in focus_texts:
            if any(word in focus for word in spec["keywords"]):
                score += 22 * count
        scores[theme] = min(96, max(18, score))
    return scores


def _dominant_desire(scores: dict[str, int], fallback_focus: str) -> dict[str, Any]:
    if not scores:
        return {
            "title": "Bugün ne aradığını birlikte öğreneceğiz",
            "confidence": 28,
            "why": "Henüz yeterli fal geçmişi yok. İlk birkaç seçimden sonra Sırra niyet ritmini daha iyi çıkarır.",
        }
    theme, score = max(scores.items(), key=lambda entry: entry[1])
    spec = _THEME_GROUPS.get(theme, {})
    title = str(spec.get("title") or fallback_focus or "Genel enerji")
    return {
        "theme": theme,
        "title": title,
        "confidence": int(score),
        "why": "Bu sinyal yalnızca uygulama içindeki odak seçimlerin, sembol tekrarların ve geri bildirimlerinden çıkarılır; dış arama geçmişi takip edilmez.",
    }


def _symbol_insight(symbol: str, count: int) -> str:
    label = _label(symbol)
    if symbol in {"kus", "kuş", "mektup", "telefon"}:
        return f"{label} tekrar ettikçe beklenen haber, mesaj veya cevap teması güçlenir."
    if symbol in {"yol", "deniz", "tren", "ucak", "uçak"}:
        return f"{label} hareket, yol, tatil ya da karar değişimi isteğini işaret edebilir."
    if symbol in {"kalp", "yuzuk", "yüzük"}:
        return f"{label} bağ kurma, netleşme ve duygusal cevap arayışıyla bağlantılıdır."
    if symbol in {"dag", "dağ", "merdiven"}:
        return f"{label} yükselme, sabır ve aşılması gereken hedef teması taşır."
    if symbol in {"anahtar", "kapi", "kapı"}:
        return f"{label} kapanmış bir konunun açılması veya yeni kapı ihtimalini anlatır."
    return f"{label} son dönemde {count} kez göründü; Sırra bunu diğer fallarla bağlamaya devam edecek."


def _demo_compass(user_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "user_id": user_id,
        "summary_title": "Sırra Haritası hazır",
        "trust_message": "Dış arama geçmişini veya başka uygulamaları takip etmiyoruz. Bu harita sadece Sırra içindeki fal seçimleri, semboller ve geri bildirimlerden oluşur.",
        "daily_symbol": {"symbol": "anahtar", "display_name": "Anahtar", "count": 1, "message": "Bugün cevap aradığın kapalı bir konuya nazikçe yaklaş."},
        "daily_message": "Bugün sende cevap alma ve yön bulma isteği öne çıkıyor. Sırra bunu kesin gelecek diye değil, kişisel niyet sinyali olarak okur.",
        "desire_signal": {"theme": "haber", "title": "Haber ve beklenen cevap", "confidence": 64, "why": "Demo modunda örnek sinyal gösteriliyor."},
        "symbol_memory": [
            {"symbol": "anahtar", "display_name": "Anahtar", "count": 2, "last_seen": now.isoformat(), "insight": "Kapalı bir konunun açılması teması tekrar ediyor."},
            {"symbol": "yol", "display_name": "Yol", "count": 1, "last_seen": now.isoformat(), "insight": "Yol, karar ve hareket enerjisini büyütür."},
        ],
        "secret_map": [
            {"id": "haber", "title": "Haber & cevap", "weight": 68, "symbols": ["anahtar", "kuş"], "message": "Beklediğin bir yanıtı kontrol etme ihtiyacı belirgin."},
            {"id": "yol", "title": "Yol & değişim", "weight": 52, "symbols": ["yol"], "message": "Kısa bir plan veya yer değiştirme fikri tetiklenebilir."},
        ],
        "cross_connections": [
            {"title": "Fallar arası bağlantı", "message": "Anahtar ve yol birlikte geldiğinde kapanan kapıdan sonra yeni rota teması doğar."}
        ],
        "time_capsules": [
            {"id": "capsule_demo", "title": "7 günlük zaman kapsülü", "unlock_at": (now + timedelta(days=7)).isoformat(), "message": "Bugünkü anahtar temasını 7 gün sonra kontrol et: cevap mı geldi, yoksa yeni kapı mı açıldı?"}
        ],
        "probability_map_30d": [
            {"topic": "Haber", "score": 68, "message": "Yakın dönemde beklenen cevapları takip etme ihtimali yüksek."},
            {"topic": "Aşk", "score": 54, "message": "Duygusal konuşma alanı açık ama kesinlik iddiası yok."},
            {"topic": "Kariyer", "score": 49, "message": "Küçük bir karar büyük yön değişimine bağlanabilir."},
        ],
        "feedback_stats": {"total": 0, "realized": 0, "partial": 0, "not_realized": 0, "unknown": 0, "trust_score": 0},
        "daily_loop": _daily_loop_items(),
        "next_best_actions": ["Bugünün sembolünü seç", "Bir fal sonucu için gerçekleşti mi işaretle", "Akşam 30 saniyelik mini niyet kontrolü yap"],
        "generated_at": _now_iso(),
    }


def _daily_loop_items() -> list[dict[str, str]]:
    return [
        {"time": "Sabah", "title": "Bugünün işareti", "message": "Tek sembol seç; uygulama gün içinde ona göre yorum dilini kişiselleştirir."},
        {"time": "Öğlen", "title": "Mini yoklama", "message": "Aşk, para, iş veya haberden hangisini aradığını tek dokunuşla belirt."},
        {"time": "Akşam", "title": "Gerçekleşti mi?", "message": "Eski yorumlara geri bildirim ver; Sırra Haritası ertesi gün daha netleşir."},
        {"time": "7 gün", "title": "Zaman kapsülü", "message": "Bugünkü ana temayı 7 gün sonra açılan notla kontrol et."},
    ]


async def build_sirra_compass(user_id: str) -> dict[str, Any]:
    db = _firestore_client_or_none()
    if db is None:
        return _demo_compass(user_id)

    try:
        now = datetime.now(UTC)
        docs = (
            db.collection("users")
            .document(user_id)
            .collection("fortunes")
            .order_by("created_at", direction="DESCENDING")
            .limit(40)
            .stream()
        )
        rows: list[dict[str, Any]] = []
        symbols: Counter[str] = Counter()
        focuses: Counter[str] = Counter()
        feedback: Counter[str] = Counter()
        last_seen: dict[str, Any] = {}
        recent_connections: list[dict[str, str]] = []
        for doc in docs:
            item = doc.to_dict() or {}
            item["fortune_id"] = str(item.get("fortune_id") or doc.id)
            rows.append(item)
            focus = _extract_focus(item)
            focuses[focus] += 1
            item_symbols = _extract_symbols(item)
            symbols.update(item_symbols)
            created_at = item.get("created_at")
            for symbol in item_symbols:
                last_seen.setdefault(symbol, created_at)
            status = str(item.get("feedback_status") or "").strip()
            if status:
                feedback[status] += 1
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            connections = payload.get("cross_fortune_connections") or payload.get("cross_connections") or []
            if isinstance(connections, list):
                for connection in connections[:2]:
                    if isinstance(connection, dict):
                        msg = str(connection.get("message") or "").strip()
                        if msg:
                            recent_connections.append({"title": "Fallar arası bağlantı", "message": msg})

        if not rows:
            demo = _demo_compass(user_id)
            demo["summary_title"] = "İlk Sırra Haritan oluşturuluyor"
            demo["daily_message"] = "İlk birkaç falından sonra sembol hafızası, gerçekleşme oranı ve 30 günlük olasılık haritası kişiselleşir."
            demo["symbol_memory"] = []
            demo["secret_map"] = []
            demo["probability_map_30d"] = []
            return demo

        top_symbols = symbols.most_common(8)
        scores = _theme_scores(symbols, focuses)
        desire = _dominant_desire(scores, focuses.most_common(1)[0][0] if focuses else "Genel enerji")
        daily_symbol_key = top_symbols[0][0] if top_symbols else "anahtar"
        daily_symbol = {
            "symbol": daily_symbol_key,
            "display_name": _label(daily_symbol_key),
            "count": int(symbols.get(daily_symbol_key, 0)),
            "last_seen": _iso(last_seen.get(daily_symbol_key)),
            "message": _symbol_insight(daily_symbol_key, int(symbols.get(daily_symbol_key, 0))),
        }
        symbol_memory = [
            {
                "symbol": symbol,
                "display_name": _label(symbol),
                "count": int(count),
                "last_seen": _iso(last_seen.get(symbol)),
                "insight": _symbol_insight(symbol, int(count)),
            }
            for symbol, count in top_symbols
        ]
        secret_map = []
        for theme, score in sorted(scores.items(), key=lambda entry: entry[1], reverse=True)[:5]:
            spec = _THEME_GROUPS[theme]
            matched = [s for s, _ in top_symbols if s in spec["symbols"]][:4]
            if score < 20 and not matched:
                continue
            secret_map.append(
                {
                    "id": theme,
                    "title": spec["title"],
                    "weight": int(score),
                    "symbols": matched,
                    "message": _theme_message(theme, int(score), matched),
                }
            )

        probability = [
            {"topic": item["title"], "score": item["weight"], "message": _probability_message(item["id"], item["weight"])}
            for item in secret_map[:4]
        ]
        total_feedback = sum(feedback.values())
        positive = feedback.get("realized", 0) + feedback.get("partial", 0)
        trust_score = int(round((positive / total_feedback) * 100)) if total_feedback else 0
        feedback_stats = {
            "total": int(total_feedback),
            "realized": int(feedback.get("realized", 0)),
            "partial": int(feedback.get("partial", 0)),
            "not_realized": int(feedback.get("not_realized", 0)),
            "unknown": int(feedback.get("unknown", 0)),
            "trust_score": trust_score,
        }
        capsules = _build_time_capsules(rows, now, daily_symbol)
        payload = {
            "user_id": user_id,
            "summary_title": "Sırra Haritan canlı",
            "trust_message": "Google aramaların, reklam geçmişin veya başka uygulamaların takip edilmez. Bu harita yalnızca Sırra içindeki fal odakların, sembollerin ve geri bildirimlerinle oluşur.",
            "daily_symbol": daily_symbol,
            "daily_message": _daily_message(desire, daily_symbol),
            "desire_signal": desire,
            "symbol_memory": symbol_memory,
            "secret_map": secret_map,
            "cross_connections": recent_connections[:4],
            "time_capsules": capsules,
            "probability_map_30d": probability,
            "feedback_stats": feedback_stats,
            "daily_loop": _daily_loop_items(),
            "next_best_actions": _next_best_actions(total_feedback, len(rows), desire),
            "generated_at": _now_iso(),
        }
        try:
            db.collection("users").document(user_id).collection("private_state").document("sirra_compass").set(
                {"last_opened_at": now, "last_desire_signal": desire, "last_daily_symbol": daily_symbol, "updated_at": now},
                merge=True,
            )
        except Exception:
            pass
        return payload
    except Exception:
        return _demo_compass(user_id)


def _theme_message(theme: str, score: int, matched: list[str]) -> str:
    labels = ", ".join(_label(s) for s in matched) if matched else "odak seçimleri"
    if theme == "ask":
        return f"{labels} aşk ve bağ kurma alanını çalıştırıyor. Kesin hüküm değil; duygusal netlik arayışı güçlü."
    if theme == "haber":
        return f"{labels} beklenen cevap, mesaj veya konuşma ihtimalini daha görünür yapıyor."
    if theme == "yol":
        return f"{labels} kısa yol, tatil fikri, taşınma ya da karar değişimi temasını besliyor."
    if theme == "kariyer":
        return f"{labels} hedef, iş, para ve görünür olma isteğini öne çıkarıyor."
    return f"{labels} sezgi, korunma ve kapalı kalan konuları işaret ediyor."


def _probability_message(theme: str, score: int) -> str:
    strength = "yüksek" if score >= 70 else "orta" if score >= 45 else "hafif"
    if theme == "ask":
        return f"30 gün içinde duygusal konuşma/mesaj alanı {strength} sinyal veriyor."
    if theme == "haber":
        return f"Beklediğin cevapları takip etme ve netleştirme ihtimali {strength}."
    if theme == "yol":
        return f"Yol, plan, tatil veya yer değişikliği düşüncesi {strength} seviyede."
    if theme == "kariyer":
        return f"İş, para veya hedef kararı alanı {strength} yoğunlukta."
    return f"Sezgi ve kapalı konu farkındalığı {strength} görünüyor."


def _daily_message(desire: dict[str, Any], daily_symbol: dict[str, Any]) -> str:
    title = str(desire.get("title") or "Genel enerji")
    symbol = str(daily_symbol.get("display_name") or "Sembol")
    return f"Bugün {title.lower()} tarafında bir cevap arıyor gibisin. {symbol} sembolü bunu destekliyor; Sırra bunu kesin gelecek değil, kişisel olasılık sinyali olarak okur."


def _build_time_capsules(rows: list[dict[str, Any]], now: datetime, daily_symbol: dict[str, Any]) -> list[dict[str, Any]]:
    capsules = []
    first = rows[0]
    created = first.get("created_at")
    created_dt = created if isinstance(created, datetime) else now
    unlock = created_dt + timedelta(days=7)
    if unlock < now:
        unlock = now + timedelta(days=1)
    capsules.append(
        {
            "id": f"capsule_{first.get('fortune_id', 'latest')}",
            "title": "7 günlük zaman kapsülü",
            "unlock_at": unlock.astimezone(UTC).isoformat(),
            "message": f"{daily_symbol.get('display_name', 'Bugünkü sembol')} temasını 7 gün sonra kontrol et: beklediğin cevap mı geldi, yoksa yön mü değişti?",
        }
    )
    return capsules


def _next_best_actions(total_feedback: int, fortune_count: int, desire: dict[str, Any]) -> list[str]:
    actions = []
    if total_feedback < max(1, fortune_count // 3):
        actions.append("Eski bir falı açıp 'Gerçekleşti mi?' işaretle; haritanın güven oranı artar.")
    actions.append(f"Bugün {desire.get('title', 'ana niyet')} için tek bir niyet seç.")
    actions.append("Akşam 30 saniyelik mini kontrol yap: Bugünkü sembol gerçek hayatta karşına çıktı mı?")
    actions.append("Bir sonraki falda aynı konuyu değil, aynı sembolü takip et; bağlantılar daha net çıkar.")
    return actions[:4]


async def record_fortune_feedback(*, user_id: str, fortune_id: str, status: str, note: str = "") -> dict[str, Any]:
<<<<<<< HEAD
    clean_status = status if status in {"realized", "partial", "not_realized", "unknown", "reported"} else "unknown"
=======
    clean_status = status if status in {"realized", "partial", "not_realized", "unknown"} else "unknown"
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    db = _firestore_client_or_none()
    if db is None:
        return {
            "status": "saved",
            "fortune_id": fortune_id,
            "feedback_status": clean_status,
<<<<<<< HEAD
            "trust_message": "Demo modunda geri bildirim kabul edildi.",
=======
            "trust_message": "Demo modunda geri bildirim kabul edildi. Gerçek Firebase bağlıyken Sırra Hafızası'na yazılır.",
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        }

    now = datetime.now(UTC)
    clean_note = (note or "").strip()[:500]
    try:
        fortune_ref = db.collection("users").document(user_id).collection("fortunes").document(fortune_id)
        fortune_ref.set(
            {
                "feedback_status": clean_status,
                "feedback_note": clean_note,
                "feedback_at": now,
                "updated_at": now,
            },
            merge=True,
        )
<<<<<<< HEAD
        if clean_status == "reported":
            db.collection("ai_content_reports").document().set(
                {
                    "user_id": user_id,
                    "fortune_id": fortune_id,
                    "reason": clean_note or "unspecified",
                    "status": "open",
                    "created_at": now,
                    "source": "fortune_result",
                }
            )
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        stats_ref = db.collection("users").document(user_id).collection("private_state").document("fortune_memory")
        snap = stats_ref.get()
        data = snap.to_dict() if snap.exists else {}
        counts = dict(data.get("feedback_counts") or {})
        counts[clean_status] = int(counts.get(clean_status) or 0) + 1
        stats_ref.set({"feedback_counts": counts, "last_feedback_at": now, "updated_at": now}, merge=True)
    except Exception:
        pass
    return {
        "status": "saved",
        "fortune_id": fortune_id,
        "feedback_status": clean_status,
<<<<<<< HEAD
        "trust_message": "İçerik bildirimin alındı ve inceleme kuyruğuna eklendi." if clean_status == "reported" else "Geri bildirimin kaydedildi. Kişisel içgörüler bundan sonra daha tutarlı hesaplanır.",
=======
        "trust_message": "Geri bildirimin kaydedildi. Sırra bundan sonra sembol tekrarlarını ve olasılık haritanı daha dürüst hesaplar.",
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    }
