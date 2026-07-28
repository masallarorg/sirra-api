import json
from uuid import uuid4


from app.core.config import settings
from app.core.errors import AppError
from app.services.openai_client import call_openai_responses, extract_output_text as extract_openai_output_text, image_data_url
from app.schemas.fortune import (
    CoffeeFortuneResult,
    DetectedSymbol,
    DreamFortuneRequest,
    DreamFortuneResult,
    FortuneSection,
    FortuneDetailBlock,
    GenericFortuneRequest,
    GenericFortuneResult,
    FollowUpQuestion,
    PersonalInsight,
    ShareCard,
    ImageRegion,
    PremiumLock,
    SymbolAnimation,
)


async def generate_coffee_fortune(
    *,
    user_id: str,
    profile: dict,
    image_bytes: list[bytes] | None = None,
    image_count: int | None = None,
) -> CoffeeFortuneResult:
    image_bytes = image_bytes or []
    if settings.mock_ai:
        return _augment_coffee_result(_mock_coffee_result(image_count=image_count or len(image_bytes) or 1), profile)

    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message="Kahve falı analiz servisi şu anda hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message="OPENAI_API_KEY is empty",
            status_code=503,
            retryable=True,
        )

    if not image_bytes:
        raise AppError(
            error_code="COFFEE_IMAGE_EMPTY",
            user_message="Kahve falı için en az 1 fotoğraf yüklemelisin.",
            developer_message="No images supplied to OpenAI coffee generator",
            status_code=422,
        )

    input_content: list[dict] = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "request_id": f"coffee_{uuid4().hex[:12]}",
                    "user_id_hash_hint": user_id[-8:],
                    "profile": profile,
                    "rules": [
                        "Fotoğrafta gerçek kahve fincanı ve telve net görünmüyorsa is_coffee=false döndür.",
                        "Görünmeyen sembol uydurma. Sadece telvede gerçekten seçilebilir şekilleri yaz.",
                        "image_region değerlerini 0-1 aralığında yaklaşık konum olarak ver.",
                        "Kesin kader garantisi, sağlık/finans/hukuk tavsiyesi verme; gelecek sinyallerini sembol ve olasılık diliyle sun.",
                        "Yorumda kullanıcıyı meraklandıran yakın gelecek sinyalleri ver; ama bunları olasılık diliyle yaz.",
                        "Eğer profil_json.focus aşk/ask ise aşk bölümünde doğrudan görülen sembollere dayanarak baş harf/iletişim enerjisi gibi merak uyandıran ama kesin olmayan ipuçları ver.",
                        "Profilde selfie_persona_enabled=true ise selfieyi kimlik veya hassas özellik çıkarmadan yalnızca sembolik persona/ifade tonu kişiselleştirmesi için kullan.",
                    ],
                },
                ensure_ascii=False,
            ),
        }
    ]

    for image in image_bytes[:3]:
        input_content.append(
            {
                "type": "input_image",
                "image_url": image_data_url(image),
            }
        )

    payload = {
        "model": settings.openai_model,
        "instructions": _coffee_developer_instructions(),
        "input": [{"role": "user", "content": input_content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "coffee_fortune_vision",
                "strict": True,
                "schema": _coffee_json_schema(),
            }
        },
    }

    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_COFFEE",
        user_message="Kahve fotoğrafları analiz edilirken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=75.0,
    )
    content = _extract_output_text(response_json)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="OPENAI_COFFEE_JSON_INVALID",
            user_message="Kahve analizi beklenen formatta gelmedi. Lütfen daha net fotoğrafla tekrar dene.",
            developer_message=f"{exc}: {content[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc

    if data.get("is_coffee") is not True:
        raise AppError(
            error_code="COFFEE_NOT_DETECTED",
            user_message=(
                "Bu fotoğrafta kahve telvesi net görünmüyor. Gerçek bir kahve falı bakabilmem için "
                "fincanın içindeki telveyi daha net, ışık yansıması az olacak şekilde çekmelisin."
            ),
            developer_message=str(data.get("rejection_reason") or "OpenAI vision rejected coffee image"),
            status_code=422,
            retryable=True,
        )

    data["fortune_id"] = data.get("fortune_id") or f"coffee_{uuid4().hex[:10]}"
    data["type"] = "coffee"
    return _augment_coffee_result(CoffeeFortuneResult.model_validate(data), profile)


async def generate_dream_fortune(request: DreamFortuneRequest) -> DreamFortuneResult:
    if settings.mock_ai:
        symbols = []
        text = request.dream_text.lower()
        if "dağ" in text or "dag" in text:
            symbols.append("dag")
        if "kuş" in text or "kus" in text:
            symbols.append("kus")
        if not symbols:
            symbols = ["yol"]

        result = DreamFortuneResult(
            fortune_id=f"dream_{uuid4().hex[:10]}",
            title="Rüyanda Tekrar Eden İşaret",
            summary="Rüyan, son dönemde zihninde büyüyen bir konunun sembollerle tekrarlandığını gösteriyor.",
            symbols=symbols,
            interpretation=(
                "Bu rüya doğrudan bir gelecek garantisi değil; ama bilinçaltında tekrar eden "
                "tema, karar vermeden önce aynı konuyu daha net görmen gerektiğini anlatıyor."
            ),
            premium_locks=[
                PremiumLock(
                    key="dream_deep_pattern",
                    title="Rüyanın Derin Sembol Haritası",
                    teaser="Rüyadaki sembollerin aşk, iş ve gelecek tarafındaki detaylı bağlantısı premiumda açılır.",
                )
            ],
        )
        return _augment_dream_result(result, request.profile)

    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message="Rüya yorumu servisi hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message="OPENAI_API_KEY is not configured",
            status_code=503,
            retryable=True,
        )

    payload = {
        "model": settings.openai_model,
        "instructions": _dream_developer_instructions(),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps({"dream_text": request.dream_text, "profile": request.profile}, ensure_ascii=False)}]}],
        "text": {"format": {"type": "json_schema", "name": "dream_fortune", "strict": True, "schema": _dream_json_schema()}},
    }
    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_DREAM",
        user_message="Rüya yorumu hazırlanırken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=60.0,
    )
    content = _extract_output_text(response_json)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="OPENAI_DREAM_JSON_INVALID",
            user_message="Rüya yorumu beklenen formatta gelmedi. Lütfen tekrar dene.",
            developer_message=f"{exc}: {content[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc
    data["fortune_id"] = data.get("fortune_id") or f"dream_{uuid4().hex[:10]}"
    data["type"] = "dream"
    return _augment_dream_result(DreamFortuneResult.model_validate(data), request.profile)


async def generate_generic_fortune(request: GenericFortuneRequest) -> GenericFortuneResult:
    allowed = {"tarot", "dream", "palm", "love", "numerology", "katina", "birthchart", "oracle", "soulmate"}
    type_id = (request.type_id or "").strip().lower()
    if type_id not in allowed:
        raise AppError(
            error_code="FORTUNE_TYPE_UNSUPPORTED",
            user_message="Bu fal türü şu anda desteklenmiyor.",
            developer_message=f"Unsupported generic fortune type: {request.type_id}",
            status_code=422,
        )

    profile = request.profile or {}
    focus = request.focus or profile.get("focus") or "Aşk"

    if settings.mock_ai:
        return _augment_generic_result(_mock_generic_result(type_id=type_id, request=request), profile, focus)

    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message="Fal yorum servisi şu anda hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message="OPENAI_API_KEY is not configured",
            status_code=503,
            retryable=True,
        )

    payload = {
        "model": settings.openai_model,
        "instructions": _generic_fortune_developer_instructions(type_id),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "request_id": f"{type_id}_{uuid4().hex[:12]}",
                                "type_id": type_id,
                                "focus": request.focus,
                                "payload": request.payload,
                                "profile": request.profile,
                                "rules": [
                                    "Kullanıcının verdiği kart, niyet, rüya, isim, tarih ve profil bilgilerine dayan.",
                                    "Mobil uygulamaya API anahtarı dönme; sadece JSON sonucu dön.",
                                    "Görülmeyen/verilmeyen bilgi uydurma. Eksik alan varsa yorumda daha genel konuş.",
                                    "Yorumu dominant işaret, gizli gerilim, olası dönüm noktası ve sakin kapanış sırasıyla kur.",
                                    "Zamanlama gerekiyorsa kesin tarih değil 3-10 gün, 2-4 hafta veya bir sonraki ay döngüsü gibi geniş pencere kullan.",
                                    "Metin sesli okunacağı için kısa-orta uzunlukta, doğal noktalama içeren Türkçe cümleler yaz.",
                                    "Kesin gelecek garantisi, sağlık/finans/hukuk tavsiyesi verme.",
                                    "Merak uyandıran yakın gelecek sinyallerini olasılık diliyle yaz.",
                                    "Aşk odağında baş harf, iletişim zamanı veya duygusal kalıp gibi ipuçlarını kesinlik iddiası olmadan ver. Örnek ton: S harfi etrafında bir isim/yer/mesaj izi belirebilir.",
                                    "Profilde daily_mood varsa yorumun tonu o ruh haline göre kişiselleştirilsin.",
                                    "Profilde selfie_persona_enabled=true ise bunu yalnızca kullanıcının açık onayıyla verilmiş sembolik yüz hattı, ifade tonu ve persona enerjisi olarak kullan; cinsiyet, yaş, kimlik, etnik köken, sağlık veya hassas özellik çıkarımı yapma.",
                                    "Selfie persona varsa yorumları daha kişisel, görsel ve merak uyandırıcı yap; örneğin bakış/ifade tonu, yüz hattının sembolik keskinliği/yumuşaklığı, aura ve karakter enerjisi gibi güvenli sembolik dil kullan.",
                                    "Doğum haritasında kullanıcının verdiği doğum tarihi, doğum saati ve doğum yeri dışına çıkma; eksik veri varsa kesin derece/ev iddiası kurma.",
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "generic_fortune_reading",
                "strict": True,
                "schema": _generic_fortune_json_schema(),
            }
        },
    }

    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_TEXT_FORTUNE",
        user_message="Fal yorumu hazırlanırken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=70.0,
    )
    content = _extract_output_text(response_json)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="OPENAI_TEXT_FORTUNE_JSON_INVALID",
            user_message="Fal yorumu beklenen formatta gelmedi. Lütfen tekrar dene.",
            developer_message=f"{exc}: {content[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc

    data["fortune_id"] = data.get("fortune_id") or f"{type_id}_{uuid4().hex[:10]}"
    data["type"] = type_id
    return _augment_generic_result(GenericFortuneResult.model_validate(data), profile, focus)


async def generate_soulmate_fortune(*, user_id: str, profile: dict, image_bytes: bytes) -> GenericFortuneResult:
    """Create a safe symbolic soulmate portrait reading from one selfie.

    This does not claim to identify a real person. It returns a symbolic fal
    interpretation plus a portrait description that the mobile app can render as an
    animated symbolic card.
    """
    if settings.mock_ai:
        request = GenericFortuneRequest(type_id="soulmate", focus=profile.get("focus") or "Aşk", payload={"theme": profile.get("theme") or "Gizemli portre", "selfie_added": True}, profile=profile)
        result = _mock_generic_result(type_id="soulmate", request=request)
        result.title = "Ruh Eşi Portresi"
        result.symbols = ["isim_enerjisi", "portre", "kalp", "zaman"]
        result.sections[0].title = "İsim enerjisi"
        result.sections[0].text = "İsim enerjisi A, M veya S harflerinde yoğunlaşıyor; bu kesin bir kimlik değil, sembolik bir izdir."
        result.sections[1].title = "Sembolik portre"
        result.sections[1].text = "Bakışları sakin, gece tonlarında ve güçlü sezgi taşıyan bir portre enerjisi öne çıkıyor."
        return _augment_generic_result(result, profile, profile.get("focus") or "Aşk")

    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message="Ruh eşi portresi şu anda hazırlanamadı. Lütfen biraz sonra tekrar dene.",
            developer_message="OPENAI_API_KEY is not configured",
            status_code=503,
            retryable=True,
        )

    input_content = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "request_id": f"soulmate_{uuid4().hex[:12]}",
                    "user_id_hash_hint": user_id[-8:],
                    "profile": profile,
                    "rules": [
                        "Gerçek ruh eşinin kimliği veya gerçek bir kişi iddiası üretme; sembolik portre ve isim enerjisi dili kullan.",
                        "Selfieyi yalnızca genel stil, enerji ve sembolik portre tonu için kullan; kimlik, yaş, etnik köken, hassas özellik veya gerçek kişi benzerliği çıkarımı yapma.",
                        "Cinsel veya uygunsuz içerik üretme. Romantik ama güvenli ve saygılı kal.",
                        "İsim enerjisi için 2-3 olası harf ver; kesin isim iddiası kurma.",
                        "Sections içinde mutlaka: İsim enerjisi, Sembolik portre, Karşılaşma enerjisi, Dikkat edilmesi gereken tema başlıkları olsun.",
                        "primary_message içinde kesin kimlik iddiası olmadığını doğal bir dille belirt.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
        {"type": "input_image", "image_url": image_data_url(image_bytes)},
    ]
    payload = {
        "model": settings.openai_model,
        "instructions": _generic_fortune_developer_instructions("soulmate"),
        "input": [{"role": "user", "content": input_content}],
        "text": {"format": {"type": "json_schema", "name": "soulmate_fortune", "strict": True, "schema": _generic_fortune_json_schema()}},
    }
    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_SOULMATE",
        user_message="Ruh eşi portresi hazırlanırken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=80.0,
    )
    content = _extract_output_text(response_json)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="OPENAI_SOULMATE_JSON_INVALID",
            user_message="Ruh eşi portresi beklenen formatta gelmedi. Lütfen tekrar dene.",
            developer_message=f"{exc}: {content[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc
    data["fortune_id"] = data.get("fortune_id") or f"soulmate_{uuid4().hex[:10]}"
    data["type"] = "soulmate"
    return _augment_generic_result(GenericFortuneResult.model_validate(data), profile, profile.get("focus") or "Genel enerji")



async def generate_palm_fortune(*, user_id: str, profile: dict, right_image_bytes: bytes, left_image_bytes: bytes) -> GenericFortuneResult:
    """Create a detailed palm reading from a real palm photo.

    The model should inspect the visible palm lines and return a structured Turkish
    entertainment reading. It must not make medical claims or biometric identity claims.
    """
    if settings.mock_ai:
        request = GenericFortuneRequest(
            type_id="palm",
            focus=profile.get("focus") or "Genel enerji",
            payload={"hand": profile.get("hand") or "Sağ ve sol el", "question": profile.get("question") or "", "right_palm_photo_added": True, "left_palm_photo_added": True},
            profile=profile,
        )
        result = _mock_generic_result(type_id="palm", request=request)
        result.title = "El Falı Detaylı Analiz"
        result.summary = "Sağ ve sol avuç içi çizgilerinde yaşam hattı, zihin hattı, kalp hattı ve kader yönü birlikte okunuyor."
        result.primary_message = "Bu yorum yüklenen sağ ve sol el fotoğraflarındaki görünen çizgilerden, iki el karşılaştırmasından ve odak alanından hazırlanmış detaylı el falıdır."
        result.sections = [
            FortuneDetailBlock(title="Fotoğraftan ilk izlenim", text="Avuç içindeki ana hatlar merkezde toplanıyor; bu, karar alırken iç ses ve mantık arasında sık gidip gelme temasını güçlendirir."),
            FortuneDetailBlock(title="Yaşam çizgisi", text="Yaşam çizgisinin akışı dayanıklılık ve yavaş güçlenme enerjisi verir. Büyük kopuşlardan çok adım adım yön değiştirme öne çıkıyor."),
            FortuneDetailBlock(title="Kalp çizgisi", text="Duygusal çizgide hassasiyet var; sevgi verirken karşı taraftan netlik bekleme ihtiyacı belirginleşiyor."),
            FortuneDetailBlock(title="Zihin çizgisi", text="Zihin çizgisi pratik ama sezgisel kararları gösterir. Yakın dönemde bir konuşmayı fazla düşünmeden önce gerçek davranışı izlemen daha doğru."),
            FortuneDetailBlock(title="Kader çizgisi", text="Kariyer tarafında tek bir kırılma değil, üst üste gelen küçük işaretler seni yeni bir karara taşıyor."),
            FortuneDetailBlock(title="Yakın dönem sinyali", text="Bir mesaj, kısa görüşme ya da ertelenmiş cevap yeniden görünür hale gelebilir; kesin değil ama iletişim enerjisi belirgin."),
        ]
        result.symbols = ["yasam_cizgisi", "kalp_cizgisi", "zihin_cizgisi", "kader_cizgisi", "mesaj"]
        return _augment_generic_result(result, profile, profile.get("focus") or "Genel enerji")

    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message="El falı analiz servisi şu anda hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message="OPENAI_API_KEY is not configured",
            status_code=503,
            retryable=True,
        )

    input_content = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "request_id": f"palm_{uuid4().hex[:12]}",
                    "user_id_hash_hint": user_id[-8:],
                    "profile": profile,
                    "rules": [
                        "Yüklenen sağ ve sol avuç içi fotoğraflarındaki görünen çizgileri ve bölgeleri temel al.",
                        "Sağ el ve sol el arasında çizgi derinliği, süreklilik, dallanma ve tepe yoğunluğu farklarını karşılaştır.",
                        "Görünmeyen çizgi veya işaret uydurma; fotoğraf net değilse bunu doğal dille belirt ve yorumu daha genel tut.",
                        "Kalp çizgisi, zihin çizgisi, yaşam çizgisi, kader çizgisi, Venüs tepesi, Ay tepesi ve parmak diplerini ayrı ayrı değerlendir.",
                        "Sections içinde mutlaka: Sağ el ilk izlenim, Sol el ilk izlenim, Yaşam çizgisi, Kalp çizgisi, Zihin çizgisi, Kader çizgisi, İki el karşılaştırması, Aşk ve ilişkiler, Kariyer/para yönü, Yakın dönem sinyali başlıklarından en az 7 tanesi olsun.",
                        "Sağlık, ömür, ölüm, hastalık, hukuki veya finansal kesin tavsiye verme; çizgi ve sembol yorumunu olasılık diliyle kur.",
                        "Biometrik kimlik, yaş, etnik köken veya hassas özellik çıkarımı yapma.",
                    ],
                },
                ensure_ascii=False,
            ),
        },
        {"type": "input_text", "text": "Aşağıdaki ilk görsel sağ el, ikinci görsel sol el avuç içidir."},
        {"type": "input_image", "image_url": image_data_url(right_image_bytes)},
        {"type": "input_image", "image_url": image_data_url(left_image_bytes)},
    ]
    payload = {
        "model": settings.openai_model,
        "instructions": _palm_developer_instructions(),
        "input": [{"role": "user", "content": input_content}],
        "text": {"format": {"type": "json_schema", "name": "palm_fortune", "strict": True, "schema": _generic_fortune_json_schema()}},
    }
    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_PALM",
        user_message="El falı hazırlanırken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=85.0,
    )
    content = _extract_output_text(response_json)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="OPENAI_PALM_JSON_INVALID",
            user_message="El falı beklenen formatta gelmedi. Lütfen tekrar dene.",
            developer_message=f"{exc}: {content[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc
    data["fortune_id"] = data.get("fortune_id") or f"palm_{uuid4().hex[:10]}"
    data["type"] = "palm"
    return _augment_generic_result(GenericFortuneResult.model_validate(data), request.profile, request.focus)


def _palm_developer_instructions() -> str:
    return """
You are the real-palm-photo reading engine for a Turkish entertainment app.
Return only valid JSON matching the schema.
Write in Turkish with a serious, premium, realistic fortune-teller tone.
Use the uploaded right-hand and left-hand palm photos as the main source: visible line depth, continuity, branches, relative placement, mounts, and two-hand comparison. Do not invent invisible details.
Do not identify the person or infer sensitive attributes. Do not make medical, life-span, death, legal, financial guarantee, or mental-health claims.
The reading is entertainment and self-reflection. Use probability language: "görünüyor", "enerji yoğunlaşıyor", "işaret ediyor", "tetiklenebilir".
Make it as detailed as a premium coffee reading: layered, sectioned, forward-looking, and tied to actual visible palm areas when possible.
""".strip()

def _extract_output_text(response_json: dict) -> str:
    return extract_openai_output_text(
        response_json,
        empty_error_code="OPENAI_OUTPUT_EMPTY",
        user_message="AI çıktısı boş geldi. Lütfen tekrar dene.",
    )




def _memory_top_symbols(profile: dict) -> list[str]:
    memory = profile.get("personal_memory") if isinstance(profile, dict) else None
    if not isinstance(memory, dict):
        return []
    return [str(s).strip() for s in (memory.get("top_symbols") or []) if str(s).strip()][:4]


def _focus_text(profile: dict, fallback: str = "Genel enerji") -> str:
    if not isinstance(profile, dict):
        return fallback
    return str(profile.get("focus") or profile.get("main_interest") or fallback).strip() or fallback


def _symbol_label(symbol: str) -> str:
    lookup = {
        "dag": "Dağ",
        "dağ": "Dağ",
        "kus": "Kuş",
        "kuş": "Kuş",
        "yol": "Yol",
        "kalp": "Kalp",
        "anahtar": "Anahtar",
        "mesaj": "Mesaj",
        "gunes": "Güneş",
        "ay": "Ay",
        "deniz": "Deniz",
        "goz": "Göz",
        "göz": "Göz",
    }
    clean = str(symbol or "").strip()
    return lookup.get(clean.lower(), clean.replace("_", " ").title())


def _build_follow_ups(focus: str, symbols: list[str]) -> list[FollowUpQuestion]:
    visible = [_symbol_label(s) for s in symbols[:3] if str(s).strip()]
    symbol_part = visible[0] if visible else "ana sembol"
    return [
        FollowUpQuestion(question=f"{symbol_part} {focus.lower()} konusunda neye işaret ediyor?", mode="symbol_detail"),
        FollowUpQuestion(question="Yakın zamanda beklediğim haber veya mesaj için ne görünüyor?", mode="near_future"),
        FollowUpQuestion(question="Bu falda dikkat etmem gereken gizli uyarı ne?", mode="warning"),
    ]


def _build_personal_insights(profile: dict, symbols: list[str], current_type: str) -> list[PersonalInsight]:
    memory_symbols = _memory_top_symbols(profile)
    insights: list[PersonalInsight] = []
    if memory_symbols:
        names = ", ".join(_symbol_label(s) for s in memory_symbols[:3])
        insights.append(PersonalInsight(title="Sırra hafızası", text=f"Geçmiş fallarında {names} temaları tekrar etmiş. Bu falda çıkan yeni işaretler aynı hikâyeyi daha kişisel bir yerden bağlıyor."))
    else:
        insights.append(PersonalInsight(title="Sırra hafızası", text="Bu fal sembol hafızana işlendi. Zamanla tekrar eden işaretler aşk, para ve kariyer yorumlarında daha kişisel bağlar kuracak."))
    if symbols:
        insights.append(PersonalInsight(title="Sembol izi", text=f"Bu yorumda {_symbol_label(symbols[0])} ana işaret olarak öne çıktı; sonraki fallarda bu işaret tekrar ederse uygulama bunu sana özel bir desen olarak gösterecek."))
    insights.append(PersonalInsight(title="Kişisel döngü", text=f"{current_type} yorumu günlük fal günlüğüne eklendi; kullanıcı isterse gerçekleşti/gerçekleşmedi takibiyle ileride daha net kişisel örüntü görebilir."))
    return insights[:3]


def _build_story_cards(title: str, summary: str, symbols: list[str]) -> list[ShareCard]:
    main_symbol = _symbol_label(symbols[0]) if symbols else "Sırra"
    short_summary = summary.strip()[:120] if summary else "Bugünün enerjisi belirginleşiyor."
    return [
        ShareCard(title=f"Bugünkü sembolüm: {main_symbol}", message=short_summary, accent="gold"),
        ShareCard(title="Fal mesajım", message="Bekleyen bir konu görünür hale geliyor; acele değil, işaretleri izleme zamanı.", accent="purple"),
    ]


def _augment_generic_result(result: GenericFortuneResult, profile: dict, focus: str | None = None) -> GenericFortuneResult:
    clean_focus = focus or _focus_text(profile)
    symbols = result.symbols or []
    if not result.follow_up_questions:
        result.follow_up_questions = _build_follow_ups(clean_focus, symbols)
    if not result.personal_insights:
        result.personal_insights = _build_personal_insights(profile or {}, symbols, result.type)
    if not result.story_cards:
        result.story_cards = _build_story_cards(result.title, result.summary, symbols)
    if not result.daily_ritual_prompt:
        result.daily_ritual_prompt = f"Bugün {clean_focus.lower()} için tek bir küçük işaret seç: mesaj mı, yol mu, sessizlik mi? Akşam bunu fal günlüğünde işaretle."
    return result


def _augment_dream_result(result: DreamFortuneResult, profile: dict) -> DreamFortuneResult:
    symbols = result.symbols or []
    if not result.follow_up_questions:
        result.follow_up_questions = _build_follow_ups(_focus_text(profile, "Rüya"), symbols)
    if not result.personal_insights:
        result.personal_insights = _build_personal_insights(profile or {}, symbols, "dream")
    if not result.story_cards:
        result.story_cards = _build_story_cards(result.title, result.summary, symbols)
    if not result.daily_ritual_prompt:
        result.daily_ritual_prompt = "Rüyadaki en güçlü sembolü gün içinde bir kez not et; aynı sembol kahve veya kart falında tekrar ederse Sırra bunu bağlayacak."
    return result


def _augment_coffee_result(result: CoffeeFortuneResult, profile: dict) -> CoffeeFortuneResult:
    symbols = [item.symbol for item in result.detected_symbols]
    if not result.follow_up_questions:
        result.follow_up_questions = _build_follow_ups(_focus_text(profile), symbols)
    if not result.personal_insights:
        result.personal_insights = _build_personal_insights(profile or {}, symbols, "coffee")
    if not result.story_cards:
        result.story_cards = _build_story_cards(result.title, result.summary, symbols)
    if not result.daily_ritual_prompt:
        result.daily_ritual_prompt = "Bugün fincanda en net gördüğün sembolü aklında tut; gün içinde benzer bir işaret görürsen fal günlüğüne ekle."
    return result

def _coffee_developer_instructions() -> str:
    return """
You are the coffee-cup vision and reading engine for a Turkish entertainment app.
Analyze the uploaded Turkish coffee cup photos. Return only valid JSON matching the schema.
First decide if the images show a real coffee cup with visible grounds/telve. If not, set is_coffee=false and explain why.
If valid, identify only visible symbols from the grounds. Do not invent symbols. Prefer traditional tasseography symbols such as bird, road, mountain, heart, key, fish, eye, tree, ring, moon, snake, door, bridge, letter, human figure.
Write Turkish text in a premium, intimate, realistic tone. The result is entertainment/fal content, not a guarantee of future events.
Write as a serious fortune reader: do not flatter the user unnecessarily, do not soften every difficult sign, and do not invent happy outcomes. If a symbol indicates delay, jealousy, distance, conflict, or an unclear person, say it clearly but respectfully.
Create curiosity and forward-looking tension in each section. Mention possible near-future events as possibilities, not certainties, such as a message, a short trip, a meeting, a delayed conversation, a first initial, or a decision window.
Open with one visually grounded dominant symbol and explain why it matters before moving to the categories.
When the cup supports timing, use broad windows such as “önümüzdeki 7-14 gün” or “bir sonraki ay döngüsü”; never promise an exact date.
Every category should contain: one observed cup clue, one possible future signal, and one calm reflection/action sentence. Avoid repeated generic boilerplate.
Write sentences that also sound natural when read aloud: moderate length, clean punctuation, no emoji, no excessive exclamation marks.
If profile.focus is aşk/ask/love, include one subtle clue in the love section: possible first letters, communication timing, or emotional pattern. Do not claim it as certain; phrase it as “enerji A/M/S harflerinde yoğunlaşıyor” or similar.
No medical, legal, financial, or mental-health advice. For money/health areas, keep language general and safe.
Detected symbols must include confidence and approximate image_region in normalized 0-1 coordinates. Symbol regions must refer to the uploaded image where the symbol is actually visible. Keep width/height reasonable, not full image.
Use the user's profile only for tone and personalization, never reveal private data.
""".strip()


def _coffee_json_schema() -> dict:
    section_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "text": {"type": "string"},
        },
        "required": ["score", "text"],
    }
    region_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "number", "minimum": 0, "maximum": 1},
            "width": {"type": "number", "minimum": 0, "maximum": 1},
            "height": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["x", "y", "width", "height"],
    }
    animation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string"},
            "asset_key": {"type": "string"},
            "duration_ms": {"type": "integer", "minimum": 400, "maximum": 5000},
        },
        "required": ["type", "asset_key", "duration_ms"],
    }
    symbol_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "symbol": {"type": "string"},
            "display_name": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "meaning": {"type": "string"},
            "image_region": region_schema,
            "image_index": {"type": "integer", "minimum": 0, "maximum": 2},
            "animation": animation_schema,
        },
        "required": ["symbol", "display_name", "confidence", "meaning", "image_region", "image_index", "animation"],
    }
    premium_lock_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "title": {"type": "string"},
            "teaser": {"type": "string"},
        },
        "required": ["key", "title", "teaser"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_coffee": {"type": "boolean"},
            "rejection_reason": {"type": "string"},
            "fortune_id": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "detected_symbols": {"type": "array", "items": symbol_schema, "minItems": 0, "maxItems": 6},
            "love": section_schema,
            "career": section_schema,
            "money": section_schema,
            "family": section_schema,
            "cross_fortune_connections": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"message": {"type": "string"}, "related_fortune_id": {"type": ["string", "null"]}, "related_symbols": {"type": "array", "items": {"type": "string"}}}, "required": ["message", "related_fortune_id", "related_symbols"]}, "maxItems": 3},
            "premium_locks": {"type": "array", "items": premium_lock_schema, "minItems": 2, "maxItems": 4},
        },
        "required": [
            "is_coffee",
            "rejection_reason",
            "fortune_id",
            "type",
            "title",
            "summary",
            "detected_symbols",
            "love",
            "career",
            "money",
            "family",
            "cross_fortune_connections",
            "premium_locks",
        ],
    }


def _mock_coffee_result(image_count: int) -> CoffeeFortuneResult:
    return CoffeeFortuneResult(
        fortune_id=f"coffee_{uuid4().hex[:10]}",
        title="Dağın Üstündeki Kuş",
        summary=(
            f"{image_count} fotoğraf üzerinden fincanın iç yüzeyinde dağ ve kuş benzeri iki güçlü sembol görünüyor. "
            "Dağ, aşılacak bir hedefi; kuş ise yakında gelecek bir haberi temsil ediyor."
        ),
        detected_symbols=[
            DetectedSymbol(
                symbol="dag",
                display_name="Dağ",
                confidence=0.82,
                meaning="Önünde büyüyen ama aşılabilir bir hedef var. Sabır ve plan gerektiriyor.",
                image_region=ImageRegion(x=0.30, y=0.42, width=0.24, height=0.20),
                image_index=1,
                animation=SymbolAnimation(type="zoom_reveal", asset_key="mountain_reveal"),
            ),
            DetectedSymbol(
                symbol="kus",
                display_name="Kuş",
                confidence=0.76,
                meaning="Beklenen bir haber veya mesajın yaklaşması.",
                image_region=ImageRegion(x=0.58, y=0.28, width=0.18, height=0.14),
                image_index=0,
                animation=SymbolAnimation(type="zoom_reveal", asset_key="bird_reveal"),
            ),
        ],
        love=FortuneSection(score=74, text="İlişkide konuşulmamış bir konu haberle veya mesajla netleşebilir. Enerji özellikle A, M veya S harflerinde yoğunlaşıyor; bu kesin bir isim değil, falın verdiği iletişim titreşimi."),
        career=FortuneSection(score=81, text="Zor görünen bir hedef var ama adım adım çıkılabilecek bir yol açılıyor. Yakın dönemde ertelenmiş bir görüşme veya cevap yeniden gündeme gelebilir."),
        money=FortuneSection(score=63, text="Para tarafında hızlı risk yerine planlı hareket daha doğru. Küçük bir rahatlama var; ama büyük karar için aceleci davranmamak gerekiyor."),
        family=FortuneSection(score=69, text="Aile içinde bekleyen bir konuşma sakinlikle çözülür. Bir kişi suskun kalmış ama tamamen uzaklaşmış görünmüyor."),
        premium_locks=[
            PremiumLock(
                key="three_month_future",
                title="3 Aylık Detaylı Gelecek Yorumu",
                teaser="Dağ sembolünün ne zaman aşılacağı ve kuşun getirdiği haberin etkisi premium analizde açılır.",
            ),
            PremiumLock(
                key="love_deep_dive",
                title="Detaylı Aşk Analizi",
                teaser="Kuş sembolünün ilişki tarafındaki gizli mesajı premiumda görünür.",
            ),
        ],
    )



def _dream_developer_instructions() -> str:
    return """
You are the dream interpretation engine for a Turkish entertainment app.
Return only valid JSON matching the schema. Interpret the user's dream in Turkish with a realistic, grounded, premium tone.
Extract only symbols that are actually present in the dream text. Connect recurring symbols gently, without claiming certainty.
No medical, legal, financial, or mental-health advice. Do not present the interpretation as fact or prophecy.
""".strip()


def _dream_json_schema() -> dict:
    premium_lock_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"key": {"type": "string"}, "title": {"type": "string"}, "teaser": {"type": "string"}},
        "required": ["key", "title", "teaser"],
    }
    connection_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message": {"type": "string"},
            "related_fortune_id": {"type": ["string", "null"]},
            "related_symbols": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["message", "related_fortune_id", "related_symbols"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fortune_id": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
            "interpretation": {"type": "string"},
            "cross_fortune_connections": {"type": "array", "items": connection_schema, "maxItems": 3},
            "premium_locks": {"type": "array", "items": premium_lock_schema, "minItems": 2, "maxItems": 4},
        },
        "required": ["fortune_id", "type", "title", "summary", "symbols", "interpretation", "cross_fortune_connections", "premium_locks"],
    }



def _generic_fortune_developer_instructions(type_id: str) -> str:
    labels = {
        "tarot": "Tarot card reader",
        "katina": "Katina love-card reader",
        "dream": "Dream symbol interpreter",
        "love": "Relationship compatibility reader",
        "numerology": "Numerology reader",
        "birthchart": "Astrology birth-chart reader",
        "oracle": "Daily oracle/energy card reader",
        "palm": "Palm-reading style interpreter",
        "soulmate": "symbolic soulmate portrait reader",
    }
    return f"""
You are the {labels.get(type_id, 'fortune reader')} engine for a serious Turkish mystical guidance app.
Return only valid JSON matching the schema.
Write in Turkish with a serious, premium, realistic fortune-teller tone.
Base the reading on the exact user input: selected cards, dream text, names, birth date, birth time, city, relationship status, focus, and profile.
Never claim certainty. Use probability language: "görünüyor", "enerji yoğunlaşıyor", "ihtimal güçleniyor", "yakın dönemde tetiklenebilir".
Do not flatter unnecessarily. If the input suggests delay, jealousy, distance, confusion, ego, silence, indecision, or emotional imbalance, say it clearly but respectfully.
Create curiosity and forward-looking tension: possible message, meeting, short trip, first initial, decision window, delayed answer, emotional conversation, or a recurring symbol. Keep it plausible and tied to input.
Use a premium narrative arc: “dominant sign → hidden tension → likely turning point → grounded closing”. The result should feel mysterious without being vague or manipulative.
When timing is supported, use broad and varied windows such as “3-10 gün”, “önümüzdeki 2-4 hafta” or “bir sonraki ay döngüsü”; never promise an exact event date.
Each section must add new information. Avoid generic repetition, absolute fate language, excessive compliments, emojis, and melodramatic threats.
Write for both reading and natural voice narration: clean punctuation, moderate sentence length, pronounceable Turkish, and no markdown symbols.
If the type is tarot/katina/oracle, interpret every selected card and how the cards connect. Do not replace the selected cards with other cards.
If the type is dream, extract only symbols mentioned in the dream text.
If the type is numerology, use the given name and birth date as input; do not invent unknown dates.
If the type is birthchart, use birth date, exact birth time, district/city, focus, and profile as the core data. Produce a detailed natal-style report with Sun/Ay/Yükselen language, element balance, houses/axes, love, career, money, family, shadow pattern, 30-day transit-style guidance, and concrete reflection prompts. If exact birth time or district/city is missing, say the rising sign and houses are approximate.
If the type is palm and no photo/line data is provided, explain that this is a symbolic palm-style reading from the selected hand and focus, not visual line detection.
If the type is soulmate, create a symbolic portrait and name-energy reading; do not claim to identify a real person or guarantee a future partner.
No medical, legal, financial, or mental-health advice. Money/career comments must stay general and safe.
Use the user's profile only for personalization and tone, never reveal private data.
""".strip()


def _generic_fortune_json_schema() -> dict:
    detail_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["title", "text"],
    }
    premium_lock_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "title": {"type": "string"},
            "teaser": {"type": "string"},
        },
        "required": ["key", "title", "teaser"],
    }
    connection_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message": {"type": "string"},
            "related_fortune_id": {"type": ["string", "null"]},
            "related_symbols": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["message", "related_fortune_id", "related_symbols"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fortune_id": {"type": "string"},
            "type": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "primary_message": {"type": "string"},
            "sections": {"type": "array", "items": detail_schema, "minItems": 4, "maxItems": 8},
            "symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
            "cross_fortune_connections": {"type": "array", "items": connection_schema, "maxItems": 3},
            "premium_locks": {"type": "array", "items": premium_lock_schema, "minItems": 2, "maxItems": 4},
        },
        "required": [
            "fortune_id",
            "type",
            "title",
            "summary",
            "primary_message",
            "sections",
            "symbols",
            "cross_fortune_connections",
            "premium_locks",
        ],
    }


def _mock_generic_result(type_id: str, request: GenericFortuneRequest) -> GenericFortuneResult:
    focus = request.focus or "Genel enerji"
    cards = request.payload.get("cards") or []
    card_text = ", ".join(str(c) for c in cards) if cards else "seçilen semboller"
    if type_id == "birthchart":
        birth_date = request.payload.get("birthDate") or request.profile.get("birth_date") or "doğum tarihi"
        birth_time = request.payload.get("birthTime") or "doğum saati"
        city = request.payload.get("city") or "doğum yeri"
        return GenericFortuneResult(
            fortune_id=f"birthchart_{uuid4().hex[:10]}",
            type="birthchart",
            title="Detaylı Doğum Haritası",
            summary=f"{birth_date} · {birth_time} · {city} verileriyle kişisel harita enerjinde sezgi, yön değişimi ve görünür olma teması öne çıkıyor.",
            primary_message="Bu rapor doğum tarihi, saat ve şehir verilerine göre hazırlanmış detaylı astrolojik rapordur; kesin kader garantisi taşımaz.",
            sections=[
                FortuneDetailBlock(title="Güneş kimliği", text="Güneş alanı öz güvenini ve dış dünyada görünmek istediğin ana yönü anlatır. Bu haritada kendini daha net ifade etme ihtiyacı güçleniyor."),
                FortuneDetailBlock(title="Ay ve iç dünya", text="Ay teması duygusal güven arayışını ve sezgisel kararlarını büyütür. Duygularını bastırmak yerine ritmini anlaman önemli."),
                FortuneDetailBlock(title="Yükselen kapısı", text="Doğum saatiyle birlikte yükselen alanı ilk izlenimini ve hayata yaklaşımını belirginleştirir. İnsanlara güçlü ama seçici açılan bir enerji var."),
                FortuneDetailBlock(title="Aşk ekseni", text="İlişkilerde netlik, sadakat ve zihinsel uyum ihtiyacı öne çıkar. Belirsiz kalan bir konuşma yakın dönemde yeniden tetiklenebilir."),
                FortuneDetailBlock(title="Kariyer ve yön", text="Kariyer alanında tek hamlelik başarıdan çok düzen kurma, görünürlük ve istikrarlı ilerleme teması baskın."),
                FortuneDetailBlock(title="Para ve değer", text="Para enerjisi öz değer algısıyla bağlantılı çalışıyor. Harcama kararlarında duygusal telafi yerine planlı seçim yapmak daha güçlü."),
                FortuneDetailBlock(title="30 günlük transit tonu", text="Yakın dönemde iletişim, karar ve geçmişten dönen bir konu ön plana çıkabilir. Acele cevap yerine zamanlama daha belirleyici."),
            ],
            symbols=["gunes", "ay", "yukselen", "venus", "mars", "transit"],
            premium_locks=[
                PremiumLock(key="relationship_axis", title="İlişki Ekseni", teaser="Venüs/Mars dili ve ilişki tetikleyicileri premium raporda derinleşir."),
                PremiumLock(key="career_timing", title="Kariyer Zamanlaması", teaser="Yakın dönem görünürlük ve karar penceresi premiumda açılır."),
            ],
        )
    return GenericFortuneResult(
        fortune_id=f"{type_id}_{uuid4().hex[:10]}",
        type=type_id,
        title=f"{focus} Yorumu",
        summary=f"{card_text} üzerinden {focus.lower()} alanında güçlü ama kontrollü bir hareket görünüyor.",
        primary_message=(
            "Seçilen işaretlerde yakın döneme açılan bir iz beliriyor; özellikle mesaj, karşılaşma veya beklenen cevap teması güçleniyor."
        ),
        sections=[
            FortuneDetailBlock(title="Ana enerji", text="Bekleyen bir konu yeniden görünür hale geliyor."),
            FortuneDetailBlock(title="Yakın dönem", text="Bir mesaj, konuşma veya küçük bir karar penceresi açılabilir."),
            FortuneDetailBlock(title="Dikkat", text="Acele karar yerine gözlem ve net soru sorma daha doğru."),
            FortuneDetailBlock(title="Sembol", text="Tekrarlayan semboller geçmiş fallarla bağlantı kurmak için saklanır."),
        ],
        symbols=["yol", "mesaj", "denge"],
        premium_locks=[
            PremiumLock(key="deep_future", title="Detaylı Yakın Gelecek", teaser="Zamanlama ve kişi enerjisi premiumda açılır."),
            PremiumLock(key="hidden_pattern", title="Gizli Bağlantı", teaser="Tekrarlayan sembollerin derin anlamı premiumda görünür."),
        ],
    )
