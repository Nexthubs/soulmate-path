/**
 * Canonical Soulmate feature contracts and constants (Spec §0, §3, §14).
 */

export const CANONICAL_QUIZ_VERSION = "soulmate-quiz-v1" as const;

export const SOULMATE_ROUTES = {
  LANDING: "/soulmate",
  QUIZ: "/soulmate/quiz",
  LOADING: "/soulmate/loading",
  EMAIL: "/soulmate/email",
  SUBSCRIBE: "/soulmate/subscribe",
  PAYMENT_PROCESSING: "/soulmate/payment-processing",
  RESULT: "/soulmate/result",
  SKETCH: "/soulmate/sketch",
  REPORT: "/soulmate/report",
} as const;

export const RESULT_KEYS = {
  USER_GENDER: "user_gender",
  PREFERRED_PARTNER_GENDER: "preferred_partner_gender",
  PREFERRED_PARTNER_AGE_RANGE: "preferred_partner_age_range",
  PREFERRED_PARTNER_ETHNICITY: "preferred_partner_ethnicity",
  KEY_SOULMATE_QUALITY: "key_soulmate_quality",
  BIRTH_DATE: "birth_date",
  DECISION_STYLE: "decision_style",
} as const;

export const UNLOCK_HOURS = {
  SKETCH: 12,
  REPORT: 24,
} as const;
