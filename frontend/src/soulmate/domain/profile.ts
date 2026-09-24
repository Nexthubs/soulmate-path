/**
 * Canonical Normalized Soulmate Profile interface and client helpers (DEV-SPEC §7, Decisions: QUIZ-01).
 *
 * NOTE: The server is the authoritative source of truth for normalized profiles.
 * Client functions are strictly for optimistic UI preview, validation, or test fixtures.
 */

import { calculateZodiacSign } from "./zodiac";

export interface SoulmateProfileV1 {
  userGender: "male" | "female";
  preferredPartnerGender: "male" | "female";
  loveLifeStatus: string;
  preferredPartnerAgeRange: string;
  preferredPartnerEthnicity: string;
  keySoulmateQuality: string;

  birthDate: string;
  zodiacSign: string;
  element: "fire" | "water" | "earth" | "wind";
  decisionStyle: "heart" | "head" | "both";

  personalChallenge: string;
  redFlag: string;
  similarityPreference: string;
  relationshipDynamic: string;
  loveLanguage: string;
  connectionStyle: string;
  relationshipFear: string;
  lifeGoals: string[];

  spiritualPerson?: boolean;
  familiarPsychicArtistry?: boolean;
  warningResponse?: "yes" | "no";
}

/**
 * Derives sketch target gender adhering to Decision QUIZ-01:
 * "q02 -> user_gender; q03 -> preferred_partner_gender. Sketch gender uses Q3."
 */
export function getSketchGender(profile: SoulmateProfileV1): "male" | "female" {
  return profile.preferredPartnerGender;
}

/**
 * Pure client-side profile mapper for optimistic local previews or test utilities.
 * Throws an Error if required answers are missing or invalid.
 */
export function buildClientSoulmateProfile(
  answers: Record<string, any>
): SoulmateProfileV1 {
  const getVal = (code: string) => {
    const raw = answers[code];
    if (raw && typeof raw === "object") {
      if ("values" in raw) return raw.values;
      if ("value" in raw) return raw.value;
    }
    return raw;
  };

  const userGender = getVal("q02");
  if (userGender !== "male" && userGender !== "female") {
    throw new Error(`Invalid or missing user gender (q02): ${userGender}`);
  }

  const preferredPartnerGender = getVal("q03");
  if (preferredPartnerGender !== "male" && preferredPartnerGender !== "female") {
    throw new Error(
      `Invalid or missing preferred partner gender (q03): ${preferredPartnerGender}`
    );
  }

  const loveLifeStatus = getVal("q04");
  const preferredPartnerAgeRange = getVal("q05");
  const preferredPartnerEthnicity = getVal("q06");
  const keySoulmateQuality = getVal("q07");
  const birthDate = getVal("q08");
  const element = getVal("q09");
  const decisionStyle = getVal("q10");
  const personalChallenge = getVal("q11");
  const redFlag = getVal("q12");
  const similarityPreference = getVal("q13");
  const relationshipDynamic = getVal("q14");
  const loveLanguage = getVal("q15");
  const connectionStyle = getVal("q16");
  const relationshipFear = getVal("q17");
  const lifeGoals = getVal("q18");

  const required = [
    ["q04", loveLifeStatus],
    ["q05", preferredPartnerAgeRange],
    ["q06", preferredPartnerEthnicity],
    ["q07", keySoulmateQuality],
    ["q08", birthDate],
    ["q09", element],
    ["q10", decisionStyle],
    ["q11", personalChallenge],
    ["q12", redFlag],
    ["q13", similarityPreference],
    ["q14", relationshipDynamic],
    ["q15", loveLanguage],
    ["q16", connectionStyle],
    ["q17", relationshipFear],
    ["q18", lifeGoals],
  ];

  for (const [code, val] of required) {
    if (!val || (Array.isArray(val) && val.length === 0)) {
      throw new Error(`Missing required quiz answer for ${code}`);
    }
  }

  const zodiac = calculateZodiacSign(birthDate);

  return {
    userGender,
    preferredPartnerGender,
    loveLifeStatus: String(loveLifeStatus),
    preferredPartnerAgeRange: String(preferredPartnerAgeRange),
    preferredPartnerEthnicity: String(preferredPartnerEthnicity),
    keySoulmateQuality: String(keySoulmateQuality),
    birthDate: String(birthDate),
    zodiacSign: zodiac.name,
    element,
    decisionStyle,
    personalChallenge: String(personalChallenge),
    redFlag: String(redFlag),
    similarityPreference: String(similarityPreference),
    relationshipDynamic: String(relationshipDynamic),
    loveLanguage: String(loveLanguage),
    connectionStyle: String(connectionStyle),
    relationshipFear: String(relationshipFear),
    lifeGoals: Array.isArray(lifeGoals) ? lifeGoals : [String(lifeGoals)],
    spiritualPerson: answers.spiritual_person ?? undefined,
    familiarPsychicArtistry: answers.familiar_psychic_artistry ?? undefined,
    warningResponse: answers.warning_response ?? undefined,
  };
}
