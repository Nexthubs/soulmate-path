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
  SETTINGS: "/soulmate/settings",
} as const;

export const ALLOWED_BACK_ROUTES = [
  SOULMATE_ROUTES.LANDING,
  SOULMATE_ROUTES.QUIZ,
  SOULMATE_ROUTES.LOADING,
  SOULMATE_ROUTES.EMAIL,
  SOULMATE_ROUTES.SUBSCRIBE,
  SOULMATE_ROUTES.RESULT,
  SOULMATE_ROUTES.SKETCH,
  SOULMATE_ROUTES.REPORT,
  SOULMATE_ROUTES.SETTINGS,
  "/login",
] as const;

/**
 * Validates and sanitizes internal back navigation targets to prevent open redirect vulnerabilities (M-2).
 */
export function sanitizeInternalRoute(
  route?: string | null,
  fallback: string = SOULMATE_ROUTES.RESULT
): string {
  if (!route) return fallback;
  // Disallow protocol-relative '//', scheme '://', or non-root starts
  if (!route.startsWith("/") || route.startsWith("//") || route.includes("://")) {
    return fallback;
  }
  const pathOnly = route.split("?")[0].split("#")[0];
  const isAllowed = ALLOWED_BACK_ROUTES.some((allowed) => allowed === pathOnly);
  return isAllowed ? route : fallback;
}

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

export * from "./report";
