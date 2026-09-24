"""Soulmate Zodiac Domain Engine (DEV-SPEC §4.4, §5.5, Decisions: AGE-01, SP-204)."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Dict, Optional, Tuple, Union
from app.core.errors import ValidationError


class ZodiacSign(str, Enum):
    """Standardized zodiac sign codes."""
    ARIES = "aries"
    TAURUS = "taurus"
    GEMINI = "gemini"
    CANCER = "cancer"
    LEO = "leo"
    VIRGO = "virgo"
    LIBRA = "libra"
    SCORPIO = "scorpio"
    SAGITTARIUS = "sagittarius"
    CAPRICORN = "capricorn"
    AQUARIUS = "aquarius"
    PISCES = "pisces"


@dataclass(frozen=True)
class ZodiacDetail:
    """Canonical details for a Western zodiac sign."""
    sign: ZodiacSign
    name: str              # e.g. "Virgo"
    sun_label: str         # e.g. "Virgo Sun"
    element: str           # "fire" | "earth" | "air" | "water"
    symbol: str            # e.g. "♍"
    start_md: Tuple[int, int]  # (month, day) start inclusive
    end_md: Tuple[int, int]    # (month, day) end inclusive


# Product-defined zodiac boundaries matching DEV-SPEC §5.5 exactly
ZODIAC_DEFINITIONS: Dict[ZodiacSign, ZodiacDetail] = {
    ZodiacSign.ARIES: ZodiacDetail(
        sign=ZodiacSign.ARIES,
        name="Aries",
        sun_label="Aries Sun",
        element="fire",
        symbol="♈",
        start_md=(3, 21),
        end_md=(4, 19),
    ),
    ZodiacSign.TAURUS: ZodiacDetail(
        sign=ZodiacSign.TAURUS,
        name="Taurus",
        sun_label="Taurus Sun",
        element="earth",
        symbol="♉",
        start_md=(4, 20),
        end_md=(5, 20),
    ),
    ZodiacSign.GEMINI: ZodiacDetail(
        sign=ZodiacSign.GEMINI,
        name="Gemini",
        sun_label="Gemini Sun",
        element="air",
        symbol="♊",
        start_md=(5, 21),
        end_md=(6, 21),
    ),
    ZodiacSign.CANCER: ZodiacDetail(
        sign=ZodiacSign.CANCER,
        name="Cancer",
        sun_label="Cancer Sun",
        element="water",
        symbol="♋",
        start_md=(6, 22),
        end_md=(7, 22),
    ),
    ZodiacSign.LEO: ZodiacDetail(
        sign=ZodiacSign.LEO,
        name="Leo",
        sun_label="Leo Sun",
        element="fire",
        symbol="♌",
        start_md=(7, 23),
        end_md=(8, 22),
    ),
    ZodiacSign.VIRGO: ZodiacDetail(
        sign=ZodiacSign.VIRGO,
        name="Virgo",
        sun_label="Virgo Sun",
        element="earth",
        symbol="♍",
        start_md=(8, 23),
        end_md=(9, 22),
    ),
    ZodiacSign.LIBRA: ZodiacDetail(
        sign=ZodiacSign.LIBRA,
        name="Libra",
        sun_label="Libra Sun",
        element="air",
        symbol="♎",
        start_md=(9, 23),
        end_md=(10, 23),
    ),
    ZodiacSign.SCORPIO: ZodiacDetail(
        sign=ZodiacSign.SCORPIO,
        name="Scorpio",
        sun_label="Scorpio Sun",
        element="water",
        symbol="♏",
        start_md=(10, 24),
        end_md=(11, 21),
    ),
    ZodiacSign.SAGITTARIUS: ZodiacDetail(
        sign=ZodiacSign.SAGITTARIUS,
        name="Sagittarius",
        sun_label="Sagittarius Sun",
        element="fire",
        symbol="♐",
        start_md=(11, 22),
        end_md=(12, 20),
    ),
    ZodiacSign.CAPRICORN: ZodiacDetail(
        sign=ZodiacSign.CAPRICORN,
        name="Capricorn",
        sun_label="Capricorn Sun",
        element="earth",
        symbol="♑",
        start_md=(12, 21),
        end_md=(1, 20),  # Crosses year boundary
    ),
    ZodiacSign.AQUARIUS: ZodiacDetail(
        sign=ZodiacSign.AQUARIUS,
        name="Aquarius",
        sun_label="Aquarius Sun",
        element="air",
        symbol="♒",
        start_md=(1, 21),
        end_md=(2, 19),
    ),
    ZodiacSign.PISCES: ZodiacDetail(
        sign=ZodiacSign.PISCES,
        name="Pisces",
        sun_label="Pisces Sun",
        element="water",
        symbol="♓",
        start_md=(2, 20),
        end_md=(3, 20),
    ),
}

# Lookup by capitalized name or lowercase code
ZODIAC_BY_NAME: Dict[str, ZodiacDetail] = {
    detail.name.lower(): detail for detail in ZODIAC_DEFINITIONS.values()
}


def get_zodiac_for_date(birth_date: Union[date, str]) -> ZodiacDetail:
    """
    Computes zodiac sign from birth date according to product-defined boundaries (DEV-SPEC §5.5).
    Accepts datetime.date or string in 'YYYY-MM-DD' format.
    Raises ValidationError on invalid string format.
    """
    if isinstance(birth_date, str):
        cleaned = birth_date.strip()
        try:
            parsed = datetime.strptime(cleaned, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError(
                f"Invalid birth date format '{birth_date}'. Expected YYYY-MM-DD."
            )
        target_date = parsed
    elif isinstance(birth_date, date):
        target_date = birth_date
    else:
        raise ValidationError(f"Unsupported birth date type: {type(birth_date).__name__}")

    m, d = target_date.month, target_date.day

    # Capricorn spans across the Gregorian year boundary: 12-21 ~ 01-20
    if (m == 1 and d <= 20) or (m == 12 and d >= 21):
        return ZODIAC_DEFINITIONS[ZodiacSign.CAPRICORN]
    elif (m == 1 and d >= 21) or (m == 2 and d <= 19):
        return ZODIAC_DEFINITIONS[ZodiacSign.AQUARIUS]
    elif (m == 2 and d >= 20) or (m == 3 and d <= 20):
        return ZODIAC_DEFINITIONS[ZodiacSign.PISCES]
    elif (m == 3 and d >= 21) or (m == 4 and d <= 19):
        return ZODIAC_DEFINITIONS[ZodiacSign.ARIES]
    elif (m == 4 and d >= 20) or (m == 5 and d <= 20):
        return ZODIAC_DEFINITIONS[ZodiacSign.TAURUS]
    elif (m == 5 and d >= 21) or (m == 6 and d <= 21):
        return ZODIAC_DEFINITIONS[ZodiacSign.GEMINI]
    elif (m == 6 and d >= 22) or (m == 7 and d <= 22):
        return ZODIAC_DEFINITIONS[ZodiacSign.CANCER]
    elif (m == 7 and d >= 23) or (m == 8 and d <= 22):
        return ZODIAC_DEFINITIONS[ZodiacSign.LEO]
    elif (m == 8 and d >= 23) or (m == 9 and d <= 22):
        return ZODIAC_DEFINITIONS[ZodiacSign.VIRGO]
    elif (m == 9 and d >= 23) or (m == 10 and d <= 23):
        return ZODIAC_DEFINITIONS[ZodiacSign.LIBRA]
    elif (m == 10 and d >= 24) or (m == 11 and d <= 21):
        return ZODIAC_DEFINITIONS[ZodiacSign.SCORPIO]
    elif (m == 11 and d >= 22) or (m == 12 and d <= 20):
        return ZODIAC_DEFINITIONS[ZodiacSign.SAGITTARIUS]
    else:
        raise ValidationError(f"Invalid calendar date: {m:02d}-{d:02d}")


def get_zodiac_by_name(name: str) -> Optional[ZodiacDetail]:
    """Retrieves ZodiacDetail by name or code case-insensitively."""
    return ZODIAC_BY_NAME.get(name.strip().lower())
