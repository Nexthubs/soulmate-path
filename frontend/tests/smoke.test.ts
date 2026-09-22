import { describe, it, expect } from "vitest";
import React from "react";
import {
  CANONICAL_QUIZ_VERSION,
  SOULMATE_ROUTES,
  RESULT_KEYS,
  UNLOCK_HOURS,
} from "../src/soulmate/domain";
import SoulmateRootPage from "../src/app/soulmate/page";

describe("Soulmate Feature Smoke & Route Namespace", () => {
  it("has canonical quiz version matching specification", () => {
    expect(CANONICAL_QUIZ_VERSION).toBe("soulmate-quiz-v1");
  });

  it("exposes all required route paths including payment-processing under /soulmate namespace", () => {
    expect(SOULMATE_ROUTES.LANDING).toBe("/soulmate");
    expect(SOULMATE_ROUTES.QUIZ).toBe("/soulmate/quiz");
    expect(SOULMATE_ROUTES.LOADING).toBe("/soulmate/loading");
    expect(SOULMATE_ROUTES.EMAIL).toBe("/soulmate/email");
    expect(SOULMATE_ROUTES.SUBSCRIBE).toBe("/soulmate/subscribe");
    expect(SOULMATE_ROUTES.PAYMENT_PROCESSING).toBe("/soulmate/payment-processing");
    expect(SOULMATE_ROUTES.RESULT).toBe("/soulmate/result");
    expect(SOULMATE_ROUTES.SKETCH).toBe("/soulmate/sketch");
    expect(SOULMATE_ROUTES.REPORT).toBe("/soulmate/report");
  });

  it("enforces immutable result mapping keys per AGENTS.md §3", () => {
    expect(RESULT_KEYS.USER_GENDER).toBe("user_gender");
    expect(RESULT_KEYS.PREFERRED_PARTNER_GENDER).toBe("preferred_partner_gender");
    expect(RESULT_KEYS.PREFERRED_PARTNER_AGE_RANGE).toBe("preferred_partner_age_range");
    expect(RESULT_KEYS.PREFERRED_PARTNER_ETHNICITY).toBe("preferred_partner_ethnicity");
    expect(RESULT_KEYS.KEY_SOULMATE_QUALITY).toBe("key_soulmate_quality");
    expect(RESULT_KEYS.BIRTH_DATE).toBe("birth_date");
    expect(RESULT_KEYS.DECISION_STYLE).toBe("decision_style");
  });

  it("enforces canonical unlock durations (12h sketch, 24h report)", () => {
    expect(UNLOCK_HOURS.SKETCH).toBe(12);
    expect(UNLOCK_HOURS.REPORT).toBe(24);
  });

  it("renders SoulmateRootPage component without error (page smoke coverage)", () => {
    const element = SoulmateRootPage();
    expect(element).toBeDefined();
    expect(React.isValidElement(element)).toBe(true);
    expect(element.type).toBe("div");
  });
});
