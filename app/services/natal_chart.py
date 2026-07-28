from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_TURKISH_SIGNS = (
    "Koç",
    "Boğa",
    "İkizler",
    "Yengeç",
    "Aslan",
    "Başak",
    "Terazi",
    "Akrep",
    "Yay",
    "Oğlak",
    "Kova",
    "Balık",
)


@dataclass(frozen=True)
class NatalSummary:
    sun_sign: str
    moon_sign: str
    rising_sign: str
    quality: str
    timezone: str
    latitude: float
    longitude: float


def _normalize_degrees(value: float) -> float:
    return value % 360.0


def _sign_from_longitude(longitude: float) -> str:
    return _TURKISH_SIGNS[int(_normalize_degrees(longitude) // 30) % 12]


def _sun_sign(date_value: datetime) -> str:
    month, day = date_value.month, date_value.day
    boundaries = (
        ((3, 21), "Koç"),
        ((4, 20), "Boğa"),
        ((5, 21), "İkizler"),
        ((6, 21), "Yengeç"),
        ((7, 23), "Aslan"),
        ((8, 23), "Başak"),
        ((9, 23), "Terazi"),
        ((10, 23), "Akrep"),
        ((11, 22), "Yay"),
        ((12, 22), "Oğlak"),
    )
    result = "Oğlak" if month == 1 else "Balık"
    for (m, d), label in boundaries:
        if (month, day) >= (m, d):
            result = label
    if month == 1 and day >= 20:
        return "Kova"
    if month == 2 and day >= 19:
        return "Balık"
    return result


def _julian_day(utc_dt: datetime) -> float:
    year = utc_dt.year
    month = utc_dt.month
    day = utc_dt.day + (
        utc_dt.hour
        + utc_dt.minute / 60.0
        + utc_dt.second / 3600.0
        + utc_dt.microsecond / 3_600_000_000.0
    ) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
    )


def _approx_moon_longitude(jd: float) -> float:
    # Low-precision lunar position adapted from classic orbital elements. It is
    # only used when Swiss Ephemeris is unavailable; production installs use
    # pyswisseph and return quality="ephemeris".
    d = jd - 2451543.5
    n = math.radians(_normalize_degrees(125.1228 - 0.0529538083 * d))
    inclination = math.radians(5.1454)
    perihelion = math.radians(_normalize_degrees(318.0634 + 0.1643573223 * d))
    eccentricity = 0.054900
    mean_anomaly_deg = _normalize_degrees(115.3654 + 13.0649929509 * d)
    mean_anomaly = math.radians(mean_anomaly_deg)
    eccentric_anomaly = mean_anomaly + eccentricity * math.sin(mean_anomaly) * (1 + eccentricity * math.cos(mean_anomaly))
    for _ in range(4):
        eccentric_anomaly -= (
            eccentric_anomaly - eccentricity * math.sin(eccentric_anomaly) - mean_anomaly
        ) / (1 - eccentricity * math.cos(eccentric_anomaly))
    x = math.cos(eccentric_anomaly) - eccentricity
    y = math.sqrt(1 - eccentricity * eccentricity) * math.sin(eccentric_anomaly)
    true_anomaly = math.atan2(y, x)
    lon_orbit = true_anomaly + perihelion
    x_ecl = math.cos(n) * math.cos(lon_orbit) - math.sin(n) * math.sin(lon_orbit) * math.cos(inclination)
    y_ecl = math.sin(n) * math.cos(lon_orbit) + math.cos(n) * math.sin(lon_orbit) * math.cos(inclination)
    longitude = math.degrees(math.atan2(y_ecl, x_ecl))

    # Main lunar perturbations improve sign-boundary reliability.
    sun_mean_anomaly = math.radians(_normalize_degrees(356.0470 + 0.9856002585 * d))
    sun_longitude = math.radians(_normalize_degrees(282.9404 + 4.70935e-5 * d)) + sun_mean_anomaly
    moon_mean_longitude = n + perihelion + mean_anomaly
    elongation = moon_mean_longitude - sun_longitude
    argument_latitude = moon_mean_longitude - n
    longitude += (
        -1.274 * math.sin(mean_anomaly - 2 * elongation)
        + 0.658 * math.sin(2 * elongation)
        - 0.186 * math.sin(sun_mean_anomaly)
        - 0.059 * math.sin(2 * mean_anomaly - 2 * elongation)
        - 0.057 * math.sin(mean_anomaly - 2 * elongation + sun_mean_anomaly)
        + 0.053 * math.sin(mean_anomaly + 2 * elongation)
        + 0.046 * math.sin(2 * elongation - sun_mean_anomaly)
        + 0.041 * math.sin(mean_anomaly - sun_mean_anomaly)
        - 0.035 * math.sin(elongation)
        - 0.031 * math.sin(mean_anomaly + sun_mean_anomaly)
        - 0.015 * math.sin(2 * argument_latitude - 2 * elongation)
        + 0.011 * math.sin(mean_anomaly - 4 * elongation)
    )
    return _normalize_degrees(longitude)


def _greenwich_sidereal_degrees(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    return _normalize_degrees(
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )


def _approx_ascendant(jd: float, latitude: float, longitude: float) -> float:
    lst = math.radians(_normalize_degrees(_greenwich_sidereal_degrees(jd) + longitude))
    t = (jd - 2451545.0) / 36525.0
    obliquity = math.radians(23.439291 - 0.0130042 * t)
    latitude_rad = math.radians(max(-66.0, min(66.0, latitude)))
    asc = math.degrees(
        math.atan2(
            -math.cos(lst),
            math.sin(lst) * math.cos(obliquity) + math.tan(latitude_rad) * math.sin(obliquity),
        )
    )
    return _normalize_degrees(asc + 180.0)


def calculate_natal_summary(
    *,
    birth_date: str,
    birth_time: str,
    latitude: float,
    longitude: float,
    timezone_name: str = "Europe/Istanbul",
) -> NatalSummary:
    try:
        local_date_time = datetime.strptime(f"{birth_date} {birth_time}", "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Doğum tarihi YYYY-AA-GG, doğum saati SS:DD formatında olmalı.") from exc

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone_name = "Europe/Istanbul"
        timezone = ZoneInfo(timezone_name)

    local_date_time = local_date_time.replace(tzinfo=timezone)
    utc_dt = local_date_time.astimezone(ZoneInfo("UTC"))
    jd = _julian_day(utc_dt)

    quality = "approximate"
    try:
        import swisseph as swe  # type: ignore

        moon_position = swe.calc_ut(jd, swe.MOON, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
        sun_position = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
        _cusps, ascmc = swe.houses_ex(jd, latitude, longitude, b"P")
        moon_longitude = float(moon_position)
        sun_sign = _sign_from_longitude(float(sun_position))
        ascendant_longitude = float(ascmc[0])
        quality = "ephemeris"
    except Exception:
        moon_longitude = _approx_moon_longitude(jd)
        sun_sign = _sun_sign(local_date_time)
        ascendant_longitude = _approx_ascendant(jd, latitude, longitude)

    return NatalSummary(
        sun_sign=sun_sign,
        moon_sign=_sign_from_longitude(moon_longitude),
        rising_sign=_sign_from_longitude(ascendant_longitude),
        quality=quality,
        timezone=timezone_name,
        latitude=round(float(latitude), 6),
        longitude=round(float(longitude), 6),
    )
