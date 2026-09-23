/**
 * Copy and dynamic text mappings for Transition screens (DEV-SPEC §5, DECISIONS.md COPY-02, COPY-03).
 */

// COPY-02: Only "intelligence" is confirmed by Figma (Node 102:320).
// Per DECISIONS.md COPY-02: Implement mapping infrastructure; do not invent production copy.
// Other options explicitly fall back to neutral placeholder copy per audit fix H-5.
export const TRANSITION_2_CONFIRMED_COPY: Record<string, string> = {
  intelligence:
    "Those who seek Intelligence in their soulmate are drawn to meaningful conversations and shared growth.",
};

export const TRANSITION_2_FALLBACK_COPY =
  "Your answer will be used to personalize this step.";

export function getTransition2Copy(quality?: string | null): string {
  if (quality) {
    const normalized = quality.toLowerCase().trim();
    if (TRANSITION_2_CONFIRMED_COPY[normalized]) {
      return TRANSITION_2_CONFIRMED_COPY[normalized];
    }
  }
  return TRANSITION_2_FALLBACK_COPY;
}

// Transition-3: Dynamic Zodiac + Decision Style copy (DEV-SPEC §5.5)
export interface Transition3Data {
  zodiacLabel?: string | null;
  decisionStyle?: string | null; // "heart" | "head" | "both"
}

export interface Transition3CopyResult {
  zodiacLabel: string;
  decisionCopy: string;
  subtitle: string;
}

export function getTransition3Copy(data?: Transition3Data | null): Transition3CopyResult {
  const zodiac = data?.zodiacLabel?.trim() || "Your Zodiac";
  const decision = data?.decisionStyle?.toLowerCase().trim();

  let decisionCopy = "people make decisions using their heart and head.";
  if (decision === "heart") {
    decisionCopy = "people make decisions using their heart.";
  } else if (decision === "head") {
    decisionCopy = "people make decisions using their head.";
  } else if (decision === "both") {
    decisionCopy = "people make decisions using their heart and head.";
  }

  const subtitle = `Many ${zodiac} individuals make decisions using their ${
    decision === "heart" ? "heart" : decision === "head" ? "head" : "heart and head"
  }.`;

  return { zodiacLabel: zodiac, decisionCopy, subtitle };
}

// COPY-03: Per DECISIONS.md COPY-03: Reproduce supported static Figma behavior only.
export const TRANSITION_4_STATIC_COPY = {
  title: "So many share this challenge",
  subtitle:
    "Moving on from the past is hard, but so many share this journey. We’ll help you find peace and clarity.",
};
