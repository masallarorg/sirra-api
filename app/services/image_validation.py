from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.core.errors import AppError

Image.MAX_IMAGE_PIXELS = 24_000_000


@dataclass
class CoffeeImageValidation:
    is_coffee: bool
    confidence: float
    reason: str


@dataclass(frozen=True)
class PreparedImage:
    bytes: bytes
    mime_type: str
    width: int
    height: int


def prepare_openai_image(
    data: bytes,
    *,
    error_prefix: str,
    user_message: str,
    min_bytes: int = 1024,
    min_edge_px: int = 160,
) -> PreparedImage:
    """Validate, normalize and compress user images before sending them to vision models.

    This protects the API from corrupt files, strips EXIF metadata, caps resolution,
    and converts everything to JPEG so the OpenAI data URL matches the real payload.
    """
    if len(data) < min_bytes:
        raise AppError(
            error_code=f"{error_prefix}_TOO_SMALL",
            user_message=user_message,
            developer_message=f"Image is {len(data)} bytes",
            status_code=422,
            retryable=True,
        )

    max_bytes = settings.max_image_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise AppError(
            error_code=f"{error_prefix}_TOO_LARGE",
            user_message="Fotoğraf çok büyük. Lütfen daha küçük veya sıkıştırılmış bir fotoğraf yükle.",
            developer_message=f"Image is {len(data)} bytes; limit is {max_bytes}",
            status_code=413,
            retryable=True,
        )

    try:
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.width < min_edge_px or image.height < min_edge_px:
                raise AppError(
                    error_code=f"{error_prefix}_RESOLUTION_TOO_LOW",
                    user_message=user_message,
                    developer_message=f"Image resolution is {image.width}x{image.height}",
                    status_code=422,
                    retryable=True,
                )
            max_edge = max(settings.max_openai_image_edge_px, 512)
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            out = BytesIO()
            image.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
            output = out.getvalue()
            return PreparedImage(bytes=output, mime_type="image/jpeg", width=image.width, height=image.height)
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(
            error_code=f"{error_prefix}_INVALID_IMAGE",
            user_message="Fotoğraf okunamadı. Lütfen gerçek bir JPG/PNG/WebP fotoğraf yükle.",
            developer_message=str(exc),
            status_code=422,
            retryable=True,
        ) from exc


async def validate_coffee_images(images: list[bytes]) -> CoffeeImageValidation:
    """Lightweight upload validation before the more expensive AI coffee check."""
    if not images:
        return CoffeeImageValidation(False, 0.0, "No images uploaded")

    try:
        for image in images:
            prepare_openai_image(
                image,
                error_prefix="COFFEE_IMAGE",
                user_message="Fotoğraf çok küçük veya okunamadı. Lütfen fincanı daha net çekip tekrar yükle.",
            )
    except AppError as exc:
        return CoffeeImageValidation(False, 0.2, exc.developer_message or exc.error_code)

    return CoffeeImageValidation(True, 0.82, "Local validation accepted")
