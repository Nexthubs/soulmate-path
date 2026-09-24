/**
 * Soulmate Zodiac Domain Logic (DEV-SPEC §4.4, §5.5, Decisions: AGE-01, SP-204).
 *
 * NOTE: The server is authoritative for all zodiac calculation, profile building,
 * and entitlement rules. This client module provides identical boundary calculations
 * for fast UI preview and formatting before server synchronization.
 */

export type ZodiacSignCode =
  | "aries"
  | "taurus"
  | "gemini"
  | "cancer"
  | "leo"
  | "virgo"
  | "libra"
  | "scorpio"
  | "sagittarius"
  | "capricorn"
  | "aquarius"
  | "pisces";

export interface ZodiacDetail {
  code: ZodiacSignCode;
  name: string;
  sunLabel: string;
  element: "fire" | "earth" | "air" | "water";
  symbol: string;
}

export const ZODIAC_DEFINITIONS: Record<ZodiacSignCode, ZodiacDetail> = {
  aries: {
    code: "aries",
    name: "Aries",
    sunLabel: "Aries Sun",
    element: "fire",
    symbol: "♈",
  },
  taurus: {
    code: "taurus",
    name: "Taurus",
    sunLabel: "Taurus Sun",
    element: "earth",
    symbol: "♉",
  },
  gemini: {
    code: "gemini",
    name: "Gemini",
    sunLabel: "Gemini Sun",
    element: "air",
    symbol: "♊",
  },
  cancer: {
    code: "cancer",
    name: "Cancer",
    sunLabel: "Cancer Sun",
    element: "water",
    symbol: "♋",
  },
  leo: {
    code: "leo",
    name: "Leo",
    sunLabel: "Leo Sun",
    element: "fire",
    symbol: "♌",
  },
  virgo: {
    code: "virgo",
    name: "Virgo",
    sunLabel: "Virgo Sun",
    element: "earth",
    symbol: "♍",
  },
  libra: {
    code: "libra",
    name: "Libra",
    sunLabel: "Libra Sun",
    element: "air",
    symbol: "♎",
  },
  scorpio: {
    code: "scorpio",
    name: "Scorpio",
    sunLabel: "Scorpio Sun",
    element: "water",
    symbol: "♏",
  },
  sagittarius: {
    code: "sagittarius",
    name: "Sagittarius",
    sunLabel: "Sagittarius Sun",
    element: "fire",
    symbol: "♐",
  },
  capricorn: {
    code: "capricorn",
    name: "Capricorn",
    sunLabel: "Capricorn Sun",
    element: "earth",
    symbol: "♑",
  },
  aquarius: {
    code: "aquarius",
    name: "Aquarius",
    sunLabel: "Aquarius Sun",
    element: "air",
    symbol: "♒",
  },
  pisces: {
    code: "pisces",
    name: "Pisces",
    sunLabel: "Pisces Sun",
    element: "water",
    symbol: "♓",
  },
};

/**
 * Calculates zodiac sign according to DEV-SPEC §5.5 product-defined boundaries.
 * Accepts ISO date string 'YYYY-MM-DD' or JavaScript Date object.
 */
export function calculateZodiacSign(birthDate: string | Date): ZodiacDetail {
  let month: number;
  let day: number;

  if (typeof birthDate === "string") {
    const parts = birthDate.trim().split("-");
    if (parts.length !== 3) {
      throw new Error(`Invalid birth date format '${birthDate}'. Expected YYYY-MM-DD.`);
    }
    month = parseInt(parts[1], 10);
    day = parseInt(parts[2], 10);
    if (isNaN(month) || isNaN(day) || month < 1 || month > 12 || day < 1 || day > 31) {
      throw new Error(`Invalid calendar date in '${birthDate}'.`);
    }
  } else if (birthDate instanceof Date) {
    month = birthDate.getUTCMonth() + 1;
    day = birthDate.getUTCDate();
  } else {
    throw new Error("Unsupported birth date type.");
  }

  // Capricorn crosses Gregorian year boundary: 12-21 ~ 01-20
  if ((month === 1 && day <= 20) || (month === 12 && day >= 21)) {
    return ZODIAC_DEFINITIONS.capricorn;
  } else if ((month === 1 && day >= 21) || (month === 2 && day <= 19)) {
    return ZODIAC_DEFINITIONS.aquarius;
  } else if ((month === 2 && day >= 20) || (month === 3 && day <= 20)) {
    return ZODIAC_DEFINITIONS.pisces;
  } else if ((month === 3 && day >= 21) || (month === 4 && day <= 19)) {
    return ZODIAC_DEFINITIONS.aries;
  } else if ((month === 4 && day >= 20) || (month === 5 && day <= 20)) {
    return ZODIAC_DEFINITIONS.taurus;
  } else if ((month === 5 && day >= 21) || (month === 6 && day <= 21)) {
    return ZODIAC_DEFINITIONS.gemini;
  } else if ((month === 6 && day >= 22) || (month === 7 && day <= 22)) {
    return ZODIAC_DEFINITIONS.cancer;
  } else if ((month === 7 && day >= 23) || (month === 8 && day <= 22)) {
    return ZODIAC_DEFINITIONS.leo;
  } else if ((month === 8 && day >= 23) || (month === 9 && day <= 22)) {
    return ZODIAC_DEFINITIONS.virgo;
  } else if ((month === 9 && day >= 23) || (month === 10 && day <= 23)) {
    return ZODIAC_DEFINITIONS.libra;
  } else if ((month === 10 && day >= 24) || (month === 11 && day <= 21)) {
    return ZODIAC_DEFINITIONS.scorpio;
  } else if ((month === 11 && day >= 22) || (month === 12 && day <= 20)) {
    return ZODIAC_DEFINITIONS.sagittarius;
  }

  throw new Error(`Invalid calendar date: ${month}-${day}`);
}

export const getZodiacForDate = calculateZodiacSign;
