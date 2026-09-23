/**
 * Copy and dynamic text mappings for Transition screens (DEV-SPEC §5, DECISIONS.md COPY-02, COPY-03).
 */

// COPY-02: Only "intelligence" is confirmed by Figma (Node 102:320).
// Per DECISIONS.md COPY-02: Implement mapping infrastructure; do not invent production copy.
// Other options explicitly fall back to the confirmed copy / TBD fallback.
export const TRANSITION_2_CONFIRMED_COPY: Record<string, string> = {
  intelligence:
    "Those who seek Intelligence in their soulmate are drawn to meaningful conversations and shared growth.",
};

export const TRANSITION_2_FALLBACK_COPY =
  "Those who seek Intelligence in their soulmate are drawn to meaningful conversations and shared growth.";

export function getTransition2Copy(quality?: string | null): string {
  if (quality) {
    const normalized = quality.toLowerCase().trim();
    if (TRANSITION_2_CONFIRMED_COPY[normalized]) {
      return TRANSITION_2_CONFIRMED_COPY[normalized];
    }
  }
  return TRANSITION_2_FALLBACK_COPY;
}

// COPY-03: Per DECISIONS.md COPY-03: Reproduce supported static Figma behavior only.
export const TRANSITION_4_STATIC_COPY = {
  title: "So many share this challenge",
  subtitle:
    "Moving on from the past is hard, but so many share this journey. We’ll help you find peace and clarity.",
};
