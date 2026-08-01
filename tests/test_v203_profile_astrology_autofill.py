from app.api.v1.routes.profile import _apply_auto_astrology


def test_profile_astrology_autofill_populates_missing_fields():
    payload = {
        "birth_date": "1990-05-15",
        "birth_time": "14:30",
        "birth_latitude": 41.0082,
        "birth_longitude": 28.9784,
        "birth_timezone": "Europe/Istanbul",
        "astrology_auto_fill": True,
        "zodiac_label": None,
        "moon_sign": None,
        "rising_sign": None,
    }

    _apply_auto_astrology(payload)

    assert payload["zodiac_label"]
    assert payload["moon_sign"]
    assert payload["rising_sign"]
    assert payload["astrology_calculation_quality"] in {"ephemeris", "approximate"}


def test_profile_astrology_autofill_does_not_break_incomplete_profile():
    payload = {
        "birth_date": "1990-05-15",
        "birth_time": None,
        "birth_latitude": None,
        "birth_longitude": None,
        "astrology_auto_fill": True,
        "moon_sign": "Eski değer",
    }

    _apply_auto_astrology(payload)

    assert payload["moon_sign"] == "Eski değer"


def test_profile_astrology_autofill_preserves_manual_values_when_disabled():
    payload = {
        "birth_date": "1990-05-15",
        "birth_time": "14:30",
        "birth_latitude": 41.0082,
        "birth_longitude": 28.9784,
        "birth_timezone": "Europe/Istanbul",
        "astrology_auto_fill": False,
        "zodiac_label": "Manuel Güneş",
        "moon_sign": "Manuel Ay",
        "rising_sign": "Manuel Yükselen",
    }

    _apply_auto_astrology(payload)

    assert payload["zodiac_label"] == "Manuel Güneş"
    assert payload["moon_sign"] == "Manuel Ay"
    assert payload["rising_sign"] == "Manuel Yükselen"
