/**
 * Tests for Frontend SoulmateProfileV1, QUIZ-01 sketch gender rule, and API client (DEV-SPEC §7, SP-205).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  buildClientSoulmateProfile,
  getSketchGender,
  SoulmateProfileV1,
} from "../src/soulmate/domain/profile";
import { getSessionProfile } from "../src/soulmate/api/session";

describe("SoulmateProfile domain and QUIZ-01", () => {
  const validAnswers = {
    q02: { value: "female" },
    q03: { value: "male" },
    q04: { value: "single" },
    q05: { value: "age_20_30" },
    q06: { value: "asian" },
    q07: { value: "loyalty" },
    q08: { value: "1994-08-25" },
    q09: { value: "fire" },
    q10: { value: "heart" },
    q11: { value: "building_trust" },
    q12: { value: "lack_of_trust" },
    q13: { value: "similar_to_me" },
    q14: { value: "deep_connection" },
    q15: { value: "words_of_affirmation" },
    q16: { value: "deep_and_intimate" },
    q17: { value: "losing_trust" },
    q18: { values: ["building_a_family", "traveling_the_world"] },
  };

  it("builds a complete SoulmateProfileV1 from valid answers", () => {
    const profile = buildClientSoulmateProfile(validAnswers);
    expect(profile.userGender).toBe("female");
    expect(profile.preferredPartnerGender).toBe("male");
    expect(profile.loveLifeStatus).toBe("single");
    expect(profile.preferredPartnerAgeRange).toBe("age_20_30");
    expect(profile.preferredPartnerEthnicity).toBe("asian");
    expect(profile.keySoulmateQuality).toBe("loyalty");
    expect(profile.birthDate).toBe("1994-08-25");
    expect(profile.zodiacSign).toBe("Virgo");
    expect(profile.element).toBe("fire");
    expect(profile.decisionStyle).toBe("heart");
    expect(profile.personalChallenge).toBe("building_trust");
    expect(profile.redFlag).toBe("lack_of_trust");
    expect(profile.similarityPreference).toBe("similar_to_me");
    expect(profile.relationshipDynamic).toBe("deep_connection");
    expect(profile.loveLanguage).toBe("words_of_affirmation");
    expect(profile.connectionStyle).toBe("deep_and_intimate");
    expect(profile.relationshipFear).toBe("losing_trust");
    expect(profile.lifeGoals).toEqual(["building_a_family", "traveling_the_world"]);
  });

  describe("QUIZ-01 — Q2/Q3 gender semantics & sketch gender", () => {
    it.each([
      ["male", "female"],
      ["female", "male"],
      ["male", "male"],
      ["female", "female"],
    ])("strictly keeps Q2 (%s) as userGender and Q3 (%s) as preferredPartnerGender", (q2, q3) => {
      const answers = {
        ...validAnswers,
        q02: { value: q2 },
        q03: { value: q3 },
      };
      const profile = buildClientSoulmateProfile(answers);
      expect(profile.userGender).toBe(q2);
      expect(profile.preferredPartnerGender).toBe(q3);

      // Crucial QUIZ-01 invariant: sketch gender MUST be preferred partner gender
      expect(getSketchGender(profile)).toBe(q3);
    });

    it("throws error if user gender or partner gender is invalid", () => {
      expect(() =>
        buildClientSoulmateProfile({ ...validAnswers, q02: "other" })
      ).toThrow("Invalid or missing user gender");

      expect(() =>
        buildClientSoulmateProfile({ ...validAnswers, q03: "other" })
      ).toThrow("Invalid or missing preferred partner gender");
    });
  });

  it("throws when required answers are missing", () => {
    const incomplete = { ...validAnswers };
    delete (incomplete as any).q05;
    expect(() => buildClientSoulmateProfile(incomplete)).toThrow("Missing required quiz answer for q05");
  });

  it("calculates zodiac sign accurately", () => {
    const ariesAnswers = { ...validAnswers, q08: { value: "2000-03-21" } };
    const p1 = buildClientSoulmateProfile(ariesAnswers);
    expect(p1.zodiacSign).toBe("Aries");

    const piscesAnswers = { ...validAnswers, q08: { value: "1996-02-29" } };
    const p2 = buildClientSoulmateProfile(piscesAnswers);
    expect(p2.zodiacSign).toBe("Pisces");
  });

  it("extracts optional interstitial responses", () => {
    const withInterstitials = {
      ...validAnswers,
      spiritual_person: true,
      familiar_psychic_artistry: false,
      warning_response: "yes",
    };
    const profile = buildClientSoulmateProfile(withInterstitials);
    expect(profile.spiritualPerson).toBe(true);
    expect(profile.familiarPsychicArtistry).toBe(false);
    expect(profile.warningResponse).toBe("yes");
  });
});

describe("getSessionProfile API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches profile successfully", async () => {
    const mockProfile: SoulmateProfileV1 = {
      userGender: "female",
      preferredPartnerGender: "male",
      loveLifeStatus: "single",
      preferredPartnerAgeRange: "age_20_30",
      preferredPartnerEthnicity: "asian",
      keySoulmateQuality: "loyalty",
      birthDate: "1994-08-25",
      zodiacSign: "Virgo",
      element: "fire",
      decisionStyle: "heart",
      personalChallenge: "building_trust",
      redFlag: "lack_of_trust",
      similarityPreference: "similar_to_me",
      relationshipDynamic: "deep_connection",
      loveLanguage: "words_of_affirmation",
      connectionStyle: "deep_and_intimate",
      relationshipFear: "losing_trust",
      lifeGoals: ["building_a_family"],
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockProfile,
    });

    const res = await getSessionProfile("ses_12345");
    expect(res).toEqual(mockProfile);
    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_12345/profile",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
  });

  it("throws parsed ApiError on 404", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({
        error_code: "NOT_FOUND",
        message: "Profile not available.",
      }),
    });

    await expect(getSessionProfile("ses_not_ready")).rejects.toThrow("Profile not available.");
  });
});
