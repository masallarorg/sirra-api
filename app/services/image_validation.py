from dataclasses import dataclass


@dataclass
class CoffeeImageValidation:
    is_coffee: bool
    confidence: float
    reason: str


async def validate_coffee_images(images: list[bytes]) -> CoffeeImageValidation:
    """Kahve fotoğrafı doğrulama katmanı.

    MVP'de mock döner. Production'da OpenAI vision veya ayrı bir CV modeli ile:
    - fincan
    - telve
    - tabak
    - telve izi
    aranır.
    """
    if not images:
        return CoffeeImageValidation(False, 0.0, "No images uploaded")

    # Basit güvenlik: çok küçük dosya gerçek fotoğraf değildir.
    if any(len(image) < 1024 for image in images):
        return CoffeeImageValidation(False, 0.15, "Image too small")

    return CoffeeImageValidation(True, 0.74, "Mock validation accepted")
