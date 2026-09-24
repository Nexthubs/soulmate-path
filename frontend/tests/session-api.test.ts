import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  continueTransition,
  createSession,
  getCurrentSession,
  getFlowState,
  getSession,
  navigateBack,
  submitAnswer,
  submitInterstitialAnswer,
} from "../src/soulmate/api/session";
import { isSoulmateApiError, isSessionMissingError, parseApiError } from "../src/soulmate/api/errors";

import { ClientConfig } from "../src/soulmate/config";

const mockConfig: ClientConfig = {
  appBaseUrl: "http://localhost:3000",
  apiBaseUrl: "http://localhost:8000/api/soulmate",
  paypalClientId: "mock_client_id",
  currency: "USD",
  introPrice: "19.00",
  regularPrice: "29.00",
};

describe("Frontend Session API Client (SP-201)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("createSession sends POST request with credentials include and returns session info", async () => {
    const mockResponsePayload = {
      session_id: "ses_abc1234567890",
      quiz_version: "soulmate-quiz-v1",
      current_step: "transition_0",
      status: "CREATED",
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => mockResponsePayload,
    } as Response);

    const result = await createSession({ utm_source: "google" }, mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ utm_json: { utm_source: "google" } }),
      })
    );
    expect(result.session_id).toBe("ses_abc1234567890");
    expect(result.quiz_version).toBe("soulmate-quiz-v1");
    expect(result.current_step).toBe("transition_0");
    expect(result.status).toBe("CREATED");
  });

  it("getCurrentSession requests /sessions/current with credentials include", async () => {
    const mockDetail = {
      session_id: "ses_abc1234567890",
      quiz_version: "soulmate-quiz-v1",
      status: "QUIZ_IN_PROGRESS",
      current_step: "q08",
      email: null,
      quiz_completed_at: null,
      answers: {
        q02: {
          question_code: "q02",
          answer: { value: "female" },
          value: "female",
          duration_ms: 2500,
          answered_at: "2026-09-23T23:00:00Z",
        },
      },
      saved_answers_count: 1,
      created_at: "2026-09-23T22:50:00Z",
      updated_at: "2026-09-23T23:00:00Z",
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDetail,
    } as Response);

    const result = await getCurrentSession(mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/current",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
    expect(result.current_step).toBe("q08");
    expect(result.answers.q02.value).toBe("female");
  });

  it("getSession requests /sessions/:sessionId and preserves step state", async () => {
    const mockDetail = {
      session_id: "ses_xyz987",
      quiz_version: "soulmate-quiz-v1",
      status: "CREATED",
      current_step: "transition_0",
      answers: {},
      saved_answers_count: 0,
      created_at: "2026-09-23T22:50:00Z",
      updated_at: "2026-09-23T22:50:00Z",
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDetail,
    } as Response);

    const result = await getSession("ses_xyz987", mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_xyz987",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
    expect(result.session_id).toBe("ses_xyz987");
  });

  it("throws typed SoulmateApiError when ownership is forbidden (403)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        error_code: "FORBIDDEN_OWNERSHIP",
        message: "Access to the requested session is forbidden.",
        request_id: "req_test_123",
      }),
    } as Response);

    try {
      await getSession("ses_someone_else", mockConfig);
      expect.fail("Should have thrown SoulmateApiError");
    } catch (err: unknown) {
      expect(isSoulmateApiError(err)).toBe(true);
      if (isSoulmateApiError(err)) {
        expect(err.errorCode).toBe("FORBIDDEN_OWNERSHIP");
        expect(err.status).toBe(403);
        expect(err.requestId).toBe("req_test_123");
      }
    }
  });

  it("throws typed SoulmateApiError when session is not found (404)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({
        error_code: "NOT_FOUND",
        message: "Session not found.",
        request_id: "req_test_404",
      }),
    } as Response);

    try {
      await getCurrentSession(mockConfig);
      expect.fail("Should have thrown SoulmateApiError");
    } catch (err: unknown) {
      expect(isSoulmateApiError(err)).toBe(true);
      if (isSoulmateApiError(err)) {
        expect(err.errorCode).toBe("NOT_FOUND");
        expect(err.status).toBe(404);
      }
    }
  });

  it("submitAnswer sends PUT to /sessions/:id/answers/:code with credentials include", async () => {
    const mockAnswerRes = {
      saved: true,
      question_code: "q02",
      next_step: "q03",
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockAnswerRes,
    } as Response);

    const result = await submitAnswer(
      "ses_abc123",
      "q02",
      { value: "female", duration_ms: 1500 },
      mockConfig
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_abc123/answers/q02",
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "female", duration_ms: 1500 }),
      })
    );
    expect(result.saved).toBe(true);
    expect(result.question_code).toBe("q02");
    expect(result.next_step).toBe("q03");
  });

  it("submitAnswer throws typed SoulmateApiError on validation error (400)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({
        error_code: "VALIDATION_ERROR",
        message: "Invalid option code 'invalid_option' for question 'q02'.",
        request_id: "req_val_400",
      }),
    } as Response);

    try {
      await submitAnswer(
        "ses_abc123",
        "q02",
        { value: "invalid_option" },
        mockConfig
      );
      expect.fail("Should have thrown SoulmateApiError");
    } catch (err: unknown) {
      expect(isSoulmateApiError(err)).toBe(true);
      if (isSoulmateApiError(err)) {
        expect(err.errorCode).toBe("VALIDATION_ERROR");
        expect(err.status).toBe(400);
      }
    }
  });

  it("getFlowState requests /sessions/:id/flow/state with credentials include", async () => {
    const mockFlowPayload = {
      session_id: "ses_abc123",
      current_step: "transition_0",
      step_type: "transition",
      next_step: "q02",
      previous_step: null,
      progress_percent: 0,
      is_quiz_completed: false,
      step_metadata: { transition_code: "transition_0" },
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockFlowPayload,
    } as Response);

    const result = await getFlowState("ses_abc123", mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_abc123/flow/state",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
    expect(result.current_step).toBe("transition_0");
    expect(result.step_type).toBe("transition");
    expect(result.next_step).toBe("q02");
    expect(result.progress_percent).toBe(0);
  });

  it("continueTransition sends POST to /sessions/:id/transitions/:code/continue", async () => {
    const mockContinuePayload = {
      transition_code: "transition_0",
      next_step: "q02",
      flow_state: {
        session_id: "ses_abc123",
        current_step: "q02",
        step_type: "question",
        next_step: "q03",
        previous_step: "transition_0",
        progress_percent: 3,
        is_quiz_completed: false,
        step_metadata: null,
      },
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockContinuePayload,
    } as Response);

    const result = await continueTransition("ses_abc123", "transition_0", mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_abc123/transitions/transition_0/continue",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      })
    );
    expect(result.transition_code).toBe("transition_0");
    expect(result.next_step).toBe("q02");
    expect(result.flow_state.current_step).toBe("q02");
  });

  it("continueTransition throws typed SoulmateApiError on 409 INVALID_FLOW_STATE", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        error_code: "INVALID_FLOW_STATE",
        message: "Cannot advance transition_1: required questions incomplete",
        request_id: "req_trans_409",
      }),
    } as Response);

    try {
      await continueTransition("ses_abc123", "transition_1", mockConfig);
      expect.fail("Should have thrown SoulmateApiError");
    } catch (err: unknown) {
      expect(isSoulmateApiError(err)).toBe(true);
      if (isSoulmateApiError(err)) {
        expect(err.errorCode).toBe("INVALID_FLOW_STATE");
        expect(err.status).toBe(409);
        expect(err.requestId).toBe("req_trans_409");
      }
    }
  });

  it("navigateBack sends POST to /sessions/:id/step/back", async () => {
    const mockBackPayload = {
      session_id: "ses_abc123",
      current_step: "q02",
      step_type: "question",
      next_step: "q03",
      previous_step: "transition_0",
      progress_percent: 3,
      is_quiz_completed: false,
      step_metadata: null,
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockBackPayload,
    } as Response);

    const result = await navigateBack("ses_abc123", mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/sessions/ses_abc123/step/back",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      })
    );
    expect(result.current_step).toBe("q02");
    expect(result.previous_step).toBe("transition_0");
  });

  describe("submitInterstitialAnswer (SP-206)", () => {
    it("sends PUT to /sessions/:id/interstitials/:code with boolean value and credentials", async () => {
      const mockPayload = {
        saved: true,
        interstitial_code: "spiritual_person",
        value: true,
        next_step: "familiar_psychic_artistry",
        flow_state: {
          session_id: "ses_abc123",
          current_step: "familiar_psychic_artistry",
          step_type: "interstitial",
          next_step: "warning_response",
          previous_step: "spiritual_person",
          progress_percent: 82,
          is_quiz_completed: true,
          step_metadata: null,
        },
      };

      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockPayload,
      } as Response);

      const result = await submitInterstitialAnswer(
        "ses_abc123",
        "spiritual_person",
        true,
        1500,
        mockConfig
      );

      expect(fetchSpy).toHaveBeenCalledWith(
        "http://localhost:8000/api/soulmate/sessions/ses_abc123/interstitials/spiritual_person",
        expect.objectContaining({
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ value: true, duration_ms: 1500 }),
        })
      );
      expect(result.saved).toBe(true);
      expect(result.interstitial_code).toBe("spiritual_person");
      expect(result.value).toBe(true);
      expect(result.next_step).toBe("familiar_psychic_artistry");
      expect(result.flow_state?.current_step).toBe("familiar_psychic_artistry");
    });

    it("sends PUT to /sessions/:id/interstitials/:code with string value ('yes' for warning_response)", async () => {
      const mockPayload = {
        saved: true,
        interstitial_code: "warning_response",
        value: "yes",
        next_step: "email",
      };

      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockPayload,
      } as Response);

      const result = await submitInterstitialAnswer(
        "ses_abc123",
        "warning_response",
        "yes",
        undefined,
        mockConfig
      );

      expect(fetchSpy).toHaveBeenCalledWith(
        "http://localhost:8000/api/soulmate/sessions/ses_abc123/interstitials/warning_response",
        expect.objectContaining({
          method: "PUT",
          credentials: "include",
          body: JSON.stringify({ value: "yes" }),
        })
      );
      expect(result.saved).toBe(true);
      expect(result.value).toBe("yes");
      expect(result.next_step).toBe("email");
    });

    it("throws typed SoulmateApiError on 409 INVALID_FLOW_STATE", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error_code: "INVALID_FLOW_STATE",
          message: "Cannot answer interstitial 'warning_response': prerequisites not answered",
          request_id: "req_interstitial_409",
        }),
      } as Response);

      try {
        await submitInterstitialAnswer("ses_abc123", "warning_response", "yes", undefined, mockConfig);
        expect.fail("Should have thrown SoulmateApiError");
      } catch (err: unknown) {
        expect(isSoulmateApiError(err)).toBe(true);
        if (isSoulmateApiError(err)) {
          expect(err.errorCode).toBe("INVALID_FLOW_STATE");
          expect(err.status).toBe(409);
          expect(err.requestId).toBe("req_interstitial_409");
        }
      }
    });
  });

  describe("Audit Remediation: Session Recovery Error Differentiation (SP-207)", () => {
    it("isSessionMissingError returns true for 401, 403, and 404", () => {
      const err401 = parseApiError(401, { error_code: "FORBIDDEN_OWNERSHIP", message: "Auth required" });
      const err403 = parseApiError(403, { error_code: "FORBIDDEN_OWNERSHIP", message: "Forbidden" });
      const err404 = parseApiError(404, { error_code: "NOT_FOUND", message: "Session not found" });

      expect(isSessionMissingError(err401)).toBe(true);
      expect(isSessionMissingError(err403)).toBe(true);
      expect(isSessionMissingError(err404)).toBe(true);
    });

    it("isSessionMissingError returns false for transient 5xx server errors and network errors", () => {
      const err500 = parseApiError(500, { error_code: "INTERNAL_SERVER_ERROR", message: "Server error" });
      const err502 = parseApiError(502, null);
      const networkErr = new TypeError("Failed to fetch");

      expect(isSessionMissingError(err500)).toBe(false);
      expect(isSessionMissingError(err502)).toBe(false);
      expect(isSessionMissingError(networkErr)).toBe(false);
    });
  });
});



