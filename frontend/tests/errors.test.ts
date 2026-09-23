import { describe, it, expect } from "vitest";
import {
  parseApiError,
  isSoulmateApiError,
  getSafeUserErrorMessage,
  SoulmateApiError,
} from "../src/soulmate/api/errors";

describe("Frontend Error Taxonomy & API Client Error Handling (SP-005)", () => {
  it("parses standard backend error payloads into typed SoulmateApiError", () => {
    const rawPayload = {
      error_code: "LOCKED_ASSET",
      message: "This artifact is locked pending scheduled unlock.",
      request_id: "req-abc-1234",
      details: { unlock_hours: 12 },
    };

    const error = parseApiError(423, rawPayload);

    expect(isSoulmateApiError(error)).toBe(true);
    expect(error.errorCode).toBe("LOCKED_ASSET");
    expect(error.message).toBe("This artifact is locked pending scheduled unlock.");
    expect(error.requestId).toBe("req-abc-1234");
    expect(error.status).toBe(423);
    expect(error.details).toEqual({ unlock_hours: 12 });
  });

  it("handles non-standard error responses gracefully", () => {
    const fallback500 = parseApiError(502, "Bad Gateway from CDN");
    expect(fallback500.errorCode).toBe("INTERNAL_SERVER_ERROR");
    expect(fallback500.status).toBe(502);

    const fallback400 = parseApiError(400, null);
    expect(fallback400.errorCode).toBe("VALIDATION_ERROR");
    expect(fallback400.status).toBe(400);
  });

  it("identifies SoulmateApiError with type guard", () => {
    const apiError = new SoulmateApiError({
      error_code: "PAYMENT_PENDING",
      message: "Payment confirming",
    });
    const standardError = new Error("Generic error");

    expect(isSoulmateApiError(apiError)).toBe(true);
    expect(isSoulmateApiError(standardError)).toBe(false);
    expect(isSoulmateApiError("some string")).toBe(false);
  });

  it("provides safe user-facing error messages for UI branching", () => {
    const paymentPending = new SoulmateApiError({
      error_code: "PAYMENT_PENDING",
      message: "We’re still confirming your payment.",
    });
    expect(getSafeUserErrorMessage(paymentPending)).toContain("confirming your payment");

    const providerUnavailable = new SoulmateApiError({
      error_code: "PROVIDER_UNAVAILABLE",
      message: "Provider down",
    });
    expect(getSafeUserErrorMessage(providerUnavailable)).toContain("Your portrait is taking a little longer");

    const invalidFlow = new SoulmateApiError({
      error_code: "INVALID_FLOW_STATE",
      message: "Step mismatch",
    });
    expect(getSafeUserErrorMessage(invalidFlow)).toContain("Returning to the current question");
  });
});
