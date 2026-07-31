import base64
import hashlib
import io
import json
import logging
import random
from uuid import uuid4


from app.core.config import settings
from app.core.errors import AppError
from app.services.openai_client import call_openai_image_generate, call_openai_responses, extract_output_text as extract_openai_output_text, image_data_url
logger = logging.getLogger("uvicorn.error")


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
        "model": settings.vision_model,
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
        timeout_seconds=120.0,
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


def _fallback_soulmate_result(*, profile: dict) -> GenericFortuneResult:
    focus = str(profile.get("focus") or "Aşk").strip() or "Aşk"
    theme = str(profile.get("theme") or "Gizemli portre").strip() or "Gizemli portre"
    request = GenericFortuneRequest(
        type_id="soulmate",
        focus=focus,
        payload={"theme": theme, "selfie_added": True},
        profile=profile,
    )
    result = _mock_generic_result(type_id="soulmate", request=request)
    result.title = "Ruh Eşi Portresi"
    result.summary = (
        "Sembolik eş enerjisinde sakin bakış, güven veren iletişim ve yavaş ama kalıcı yakınlaşma teması öne çıkıyor."
    )
    result.primary_message = (
        "Bu portre gerçek bir kişinin kimliğini tespit etmez; ilişki odağından üretilmiş kurgusal ve sembolik bir eş arketipidir."
    )
    result.symbols = ["ay_isigi", "sakin_bakis", "guven", "mesaj", "yeni_baslangic"]
    result.sections = [
        FortuneDetailBlock(
            title="İsim enerjisi",
            text="A, M ve S harfleri çevresinde bir isim, yer veya mesaj izi beliriyor; bu kesin isim değil, sembolik bir işarettir.",
        ),
        FortuneDetailBlock(
            title="Sembolik portre",
            text="Duru bakışlı, sakin ama güçlü karakterli, ilk anda mesafeli; güven oluştuğunda koruyucu ve açık iletişim kuran bir arketip görünür.",
        ),
        FortuneDetailBlock(
            title="Karşılaşma enerjisi",
            text="Gündelik bir iş, kısa yol, ortak çevre ya da beklenmedik bir mesaj üzerinden gelişen tanışma olasılığı güçleniyor.",
        ),
        FortuneDetailBlock(
            title="Dikkat edilmesi gereken tema",
            text="Hızlı kesinlik aramak yerine davranış tutarlılığına bakmak ve duygusal sınırlarını net tutmak bu dönemde daha koruyucu.",
        ),
    ]
    return result


def _local_graphite_soulmate_portrait(*, user_id: str, profile: dict, reading: GenericFortuneResult) -> tuple[str, str]:
    """Create a deterministic local graphite-style fallback portrait.

    The drawing is deliberately fictional and does not copy or infer the face in
    the uploaded selfie. It keeps the soulmate endpoint usable when the remote
    image-generation service is temporarily unavailable.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    seed_source = "|".join(
        [
            user_id,
            str(profile.get("focus") or "Aşk"),
            str(profile.get("theme") or "Gizemli portre"),
            reading.summary,
        ]
    )
    seed = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    size = 768

    paper = Image.new("RGB", (size, size), (246, 242, 232))
    noise = Image.effect_noise((size, size), 18).convert("L")
    noise = ImageOps.colorize(noise, black=(218, 213, 202), white=(255, 253, 247))
    paper = Image.blend(paper, noise, 0.16)

    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    cx = size // 2 + rng.randint(-18, 18)
    face_top = 138 + rng.randint(-8, 12)
    face_w = 286 + rng.randint(-18, 22)
    face_h = 380 + rng.randint(-12, 26)
    face_box = (cx - face_w // 2, face_top, cx + face_w // 2, face_top + face_h)

    # Soft graphite shadows beneath hair, cheekbones, jaw and shoulders.
    shade_draw.ellipse((face_box[0] - 22, face_box[1] - 30, face_box[2] + 22, face_box[3] + 14), fill=(20, 20, 20, 28))
    shade_draw.ellipse((face_box[0] + 24, face_box[1] + 110, cx + 4, face_box[3] - 44), fill=(30, 30, 30, 28))
    shade_draw.ellipse((cx - 4, face_box[1] + 126, face_box[2] - 20, face_box[3] - 58), fill=(30, 30, 30, 20))
    shade_draw.ellipse((cx - 250, face_box[3] - 10, cx + 250, size + 150), fill=(20, 20, 20, 34))
    shade = shade.filter(ImageFilter.GaussianBlur(24))
    paper = Image.alpha_composite(paper.convert("RGBA"), shade)

    draw = ImageDraw.Draw(paper)
    graphite = (55, 53, 50, 255)
    mid = (100, 96, 90, 255)
    light = (220, 215, 205, 255)

    # Shoulders and neck.
    neck_w = 88 + rng.randint(-8, 12)
    neck_top = face_box[3] - 42
    draw.line((cx - neck_w // 2, neck_top, cx - neck_w // 2 - 8, neck_top + 120), fill=mid, width=4)
    draw.line((cx + neck_w // 2, neck_top, cx + neck_w // 2 + 8, neck_top + 120), fill=mid, width=4)
    draw.arc((cx - 300, face_box[3] + 32, cx + 300, size + 220), 198, 342, fill=graphite, width=6)
    draw.arc((cx - 258, face_box[3] + 72, cx + 258, size + 180), 202, 338, fill=mid, width=3)

    # Face outline and ears.
    draw.ellipse(face_box, fill=(232, 227, 217, 255), outline=graphite, width=5)
    ear_h = 94
    ear_y = face_top + face_h // 2 - ear_h // 2
    draw.arc((face_box[0] - 24, ear_y, face_box[0] + 22, ear_y + ear_h), 78, 282, fill=mid, width=4)
    draw.arc((face_box[2] - 22, ear_y, face_box[2] + 24, ear_y + ear_h), 258, 102, fill=mid, width=4)

    # Hair varies deterministically between short, wavy and shoulder-length.
    hair_style = seed % 3
    hair_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hair_layer)
    if hair_style == 0:
        hd.pieslice((face_box[0] - 26, face_top - 68, face_box[2] + 28, face_top + 172), 178, 362, fill=(48, 46, 44, 225))
        hd.polygon([(face_box[0] - 6, face_top + 38), (cx - 62, face_top - 16), (cx - 10, face_top + 54), (cx + 52, face_top - 12), (face_box[2] + 8, face_top + 46), (face_box[2] - 4, face_top - 12), (face_box[0] + 8, face_top - 8)], fill=(52, 50, 47, 235))
    elif hair_style == 1:
        hd.ellipse((face_box[0] - 48, face_top - 54, face_box[2] + 46, face_box[3] + 62), fill=(56, 53, 50, 210))
        hd.ellipse((face_box[0] + 18, face_top + 12, face_box[2] - 18, face_box[3] + 10), fill=(0, 0, 0, 0))
        for i in range(11):
            x = face_box[0] - 24 + i * (face_w + 48) / 10
            hd.arc((x - 26, face_top - 12, x + 42, face_box[3] + 52), 84, 276, fill=(32, 31, 30, 170), width=5)
    else:
        hd.ellipse((face_box[0] - 38, face_top - 62, face_box[2] + 38, face_top + 180), fill=(45, 43, 41, 232))
        hd.polygon([(face_box[0] - 28, face_top + 80), (face_box[0] + 34, face_box[3] + 126), (cx - 92, face_box[3] + 54), (cx - 48, face_top + 30)], fill=(48, 46, 44, 220))
        hd.polygon([(face_box[2] + 28, face_top + 80), (face_box[2] - 34, face_box[3] + 126), (cx + 92, face_box[3] + 54), (cx + 48, face_top + 30)], fill=(48, 46, 44, 220))
    hair_layer = hair_layer.filter(ImageFilter.GaussianBlur(1.0))
    paper = Image.alpha_composite(paper, hair_layer)
    draw = ImageDraw.Draw(paper)

    # Eyes, brows and facial structure.
    eye_y = face_top + 158 + rng.randint(-5, 5)
    eye_gap = 62 + rng.randint(-4, 6)
    eye_w = 48 + rng.randint(-4, 5)
    for side in (-1, 1):
        ex = cx + side * eye_gap
        draw.arc((ex - eye_w, eye_y - 18, ex + eye_w, eye_y + 24), 195, 345, fill=graphite, width=4)
        draw.ellipse((ex - 8, eye_y - 2, ex + 8, eye_y + 14), fill=(58, 56, 53, 255))
        draw.ellipse((ex - 3, eye_y + 2, ex + 3, eye_y + 8), fill=(20, 20, 20, 255))
        brow_y = eye_y - 34 + rng.randint(-2, 3)
        draw.arc((ex - eye_w - 4, brow_y - 10, ex + eye_w + 2, brow_y + 18), 196, 340, fill=graphite, width=5)

    nose_top = eye_y + 12
    nose_bottom = face_top + 258 + rng.randint(-4, 8)
    draw.line((cx - 2, nose_top, cx - 12, nose_bottom - 10), fill=mid, width=3)
    draw.arc((cx - 28, nose_bottom - 18, cx + 30, nose_bottom + 20), 24, 156, fill=mid, width=3)

    mouth_y = face_top + 304 + rng.randint(-4, 7)
    mouth_w = 66 + rng.randint(-6, 12)
    draw.arc((cx - mouth_w, mouth_y - 18, cx + mouth_w, mouth_y + 22), 202, 338, fill=graphite, width=3)
    draw.arc((cx - mouth_w + 10, mouth_y - 2, cx + mouth_w - 10, mouth_y + 30), 20, 160, fill=mid, width=2)
    draw.arc((cx - 72, face_box[3] - 92, cx + 72, face_box[3] - 20), 18, 162, fill=light, width=3)

    # Fine graphite hatching and paper grain around the silhouette.
    stroke_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stroke_layer)
    for _ in range(1250):
        angle_bias = rng.choice((-1, 1))
        x = rng.randint(max(20, face_box[0] - 90), min(size - 20, face_box[2] + 90))
        y = rng.randint(max(20, face_top - 90), min(size - 20, face_box[3] + 150))
        length = rng.randint(5, 24)
        alpha = rng.randint(8, 28)
        sd.line((x, y, x + angle_bias * length, y + rng.randint(2, 14)), fill=(35, 34, 32, alpha), width=1)
    stroke_layer = stroke_layer.filter(ImageFilter.GaussianBlur(0.25))
    paper = Image.alpha_composite(paper, stroke_layer).convert("RGB")
    paper = paper.filter(ImageFilter.UnsharpMask(radius=1.4, percent=115, threshold=3))

    output = io.BytesIO()
    paper.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
    return base64.b64encode(output.getvalue()).decode("ascii"), "image/jpeg"


async def generate_soulmate_fortune(*, user_id: str, profile: dict, image_bytes: bytes) -> GenericFortuneResult:
    """Create a symbolic fictional counterpart portrait from one selfie.

    Remote analysis and image generation are preferred. A local deterministic
    graphite portrait is returned when either remote stage is unavailable, so a
    temporary upstream error never turns the whole interpretation into HTTP 502.
    """
    safe_profile = profile if isinstance(profile, dict) else {}
    focus = str(safe_profile.get("focus") or "Aşk").strip() or "Aşk"
    result: GenericFortuneResult | None = None

    if settings.mock_ai or not settings.openai_api_key:
        if not settings.mock_ai:
            logger.warning("Soulmate remote analysis skipped: OPENAI_API_KEY is not configured; using local fallback")
        result = _fallback_soulmate_result(profile=safe_profile)
    else:
        input_content = [
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "request_id": f"soulmate_{uuid4().hex[:12]}",
                        "user_id_hash_hint": user_id[-8:],
                        "profile": safe_profile,
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
            "model": settings.vision_model,
            "instructions": _generic_fortune_developer_instructions("soulmate"),
            "input": [{"role": "user", "content": input_content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "soulmate_fortune",
                    "strict": True,
                    "schema": _generic_fortune_json_schema(),
                }
            },
        }
        try:
            response_json = await call_openai_responses(
                payload,
                error_code="OPENAI_SOULMATE",
                user_message="Ruh eşi portresi hazırlanırken sorun oluştu. Lütfen tekrar dene.",
                timeout_seconds=150.0,
            )
            content = _extract_output_text(response_json)
            data = json.loads(content)
            data["fortune_id"] = data.get("fortune_id") or f"soulmate_{uuid4().hex[:10]}"
            data["type"] = "soulmate"
            result = GenericFortuneResult.model_validate(data)
        except Exception as exc:
            error_code = getattr(exc, "error_code", type(exc).__name__)
            logger.warning("Soulmate analysis fallback activated code=%s", error_code)
            result = _fallback_soulmate_result(profile=safe_profile)

    assert result is not None
    symbols_hint = ", ".join(str(item) for item in result.symbols[:6])
    portrait_prompt = f"""
Create a premium graphite pencil portrait on textured ivory paper of exactly one fictional adult romantic counterpart.
This must be a newly invented person, not the customer from the uploaded selfie and not a copy or transformation of any real face.
The selfie was used only upstream to understand the customer's requested mood; it is not an image reference for this generation.
Draw a plausible compatible partner archetype with expressive eyes, natural adult anatomy, professional charcoal and graphite detail,
subtle mystical light, clean ivory-paper background, no text, no logos, no frame, and no second person.
Theme: {safe_profile.get('theme') or 'Gizemli portre'}.
Relationship focus: {focus}.
Reading mood: {result.summary or result.primary_message or 'sakin, güven veren ve gizemli'}.
Symbolic cues: {symbols_hint or 'ay ışığı, sakin bağ ve yeni başlangıç'}.
The portrait is fictional entertainment and must not claim to identify a real current or future spouse.
""".strip()

    portrait_base64: str
    portrait_mime_type: str
    if settings.mock_ai or not settings.openai_api_key:
        portrait_base64, portrait_mime_type = _local_graphite_soulmate_portrait(
            user_id=user_id,
            profile=safe_profile,
            reading=result,
        )
    else:
        try:
            portrait_base64, portrait_mime_type = await call_openai_image_generate(
                prompt=portrait_prompt,
                error_code="OPENAI_SOULMATE_PORTRAIT",
                user_message="Ruh eşi kara kalem portresi hazırlanırken sorun oluştu. Lütfen tekrar dene.",
                output_format="jpeg",
                quality="medium",
                size="1024x1024",
                timeout_seconds=180.0,
            )
        except Exception as exc:
            error_code = getattr(exc, "error_code", type(exc).__name__)
            logger.warning("Soulmate portrait local fallback activated code=%s", error_code)
            portrait_base64, portrait_mime_type = _local_graphite_soulmate_portrait(
                user_id=user_id,
                profile=safe_profile,
                reading=result,
            )

    result.fortune_id = result.fortune_id or f"soulmate_{uuid4().hex[:10]}"
    result.type = "soulmate"
    result.portrait_image_base64 = portrait_base64
    result.portrait_mime_type = portrait_mime_type
    return _augment_generic_result(result, safe_profile, focus)


async def generate_palm_fortune(*, user_id: str, profile: dict, right_image_bytes: bytes, left_image_bytes: bytes) -> GenericFortuneResult:
    """Create a detailed palm reading from real right/left palm photos.

    The model should inspect the visible palm lines and return a structured Turkish
    entertainment reading. It must not make medical claims or biometric identity claims.
    """
    safe_profile = profile if isinstance(profile, dict) else {}
    focus = str(safe_profile.get("focus") or "Genel enerji").strip() or "Genel enerji"

    if settings.mock_ai:
        request = GenericFortuneRequest(
            type_id="palm",
            focus=focus,
            payload={"hand": safe_profile.get("hand") or "Sağ ve sol el", "question": safe_profile.get("question") or "", "right_palm_photo_added": True, "left_palm_photo_added": True},
            profile=safe_profile,
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
        return _augment_generic_result(result, safe_profile, focus)

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
                    "profile": safe_profile,
                    "focus": focus,
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
        "model": settings.vision_model,
        "instructions": _palm_developer_instructions(),
        "input": [{"role": "user", "content": input_content}],
        "text": {"format": {"type": "json_schema", "name": "palm_fortune", "strict": True, "schema": _generic_fortune_json_schema()}},
    }
    response_json = await call_openai_responses(
        payload,
        error_code="OPENAI_PALM",
        user_message="El falı hazırlanırken sorun oluştu. Lütfen tekrar dene.",
        timeout_seconds=130.0,
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
    return _augment_generic_result(GenericFortuneResult.model_validate(data), safe_profile, focus)


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
