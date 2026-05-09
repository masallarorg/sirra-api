from app.schemas.fortune import CrossFortuneConnection

SYMBOL_GROUPS = {
    "yukselis": {"dag", "merdiven", "yol", "zirve"},
    "haber": {"kus", "mektup", "telefon", "anahtar"},
    "iliski": {"kalp", "yuzuk", "iki_kisi", "cicek"},
    "gizli_konu": {"yilan", "golge", "kapali_kapi", "goz"},
}


async def find_cross_fortune_connections(
    user_id: str,
    new_symbols: list[str],
) -> list[CrossFortuneConnection]:
    """Yeni sembolleri kullanıcının geçmiş sembolleriyle bağlar.

    MVP'de demo bağlantı döner. Production'da Firestore users/{userId}/symbols
    koleksiyonu sorgulanacak.
    """
    normalized = set(new_symbols)

    if "dag" in normalized:
        return [
            CrossFortuneConnection(
                message=(
                    "Dağ sembolü tekrar ediyor. Daha önceki fal geçmişinde de yükselme, "
                    "engel ve sabır teması görünmüştü. Bu rastgele bir tekrar gibi durmuyor."
                ),
                related_fortune_id="demo_previous_dream_001",
                related_symbols=["dag", "yol"],
            )
        ]

    for group_name, group_symbols in SYMBOL_GROUPS.items():
        if normalized.intersection(group_symbols):
            return [
                CrossFortuneConnection(
                    message=f"Bu sembol {group_name} temasıyla geçmiş yorumlarınla bağlantılı olabilir.",
                    related_symbols=sorted(normalized.intersection(group_symbols)),
                )
            ]

    return []
