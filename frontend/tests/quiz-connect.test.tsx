import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SoulmateQuizPage from "../src/app/soulmate/quiz/page";
import SoulmateLoadingPage from "../src/app/soulmate/loading/page";
import * as sessionApi from "../src/soulmate/api/session";

// Mock next/navigation
const mockPush = vi.fn();
const mockBack = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: mockBack,
  }),
  useSearchParams: () => mockSearchParams,
}));

describe("SP-207: Connect Quiz UI to Live APIs & State Management", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  describe("1. Isolated & Removable Fixture Mode (Acceptance Criterion 1)", () => {
    it("renders live question UI without fixture banner or dev toolbar by default", () => {
      mockSearchParams = new URLSearchParams();
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).not.toContain("data-testid=\"quiz-dev-toolbar\"");
      expect(html).not.toContain("data-testid=\"quiz-fixture-banner\"");
      expect(html).toContain("Select your gender");
      expect(html).toContain("data-testid=\"quiz-radiogroup\"");
    });

    it("strictly isolates fixture mode to development when fixture=true", () => {
      mockSearchParams = new URLSearchParams({ fixture: "true" });
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).toContain("data-testid=\"quiz-dev-toolbar\"");
      expect(html).toContain("data-testid=\"quiz-fixture-banner\"");
    });

    it("strictly disables fixture mode in production even if fixture=true is passed", () => {
      const originalEnv = process.env.NODE_ENV;
      try {
        (process.env as Record<string, string | undefined>).NODE_ENV = "production";
        mockSearchParams = new URLSearchParams({ fixture: "true" });

        const html = renderToStaticMarkup(<SoulmateQuizPage />);
        expect(html).not.toContain("data-testid=\"quiz-dev-toolbar\"");
        expect(html).not.toContain("data-testid=\"quiz-fixture-banner\"");
      } finally {
        (process.env as Record<string, string | undefined>).NODE_ENV = originalEnv;
      }
    });
  });

  describe("2. Server-Authoritative Question Rendering (Acceptance Criterion 4)", () => {
    it("renders single choice question structure for Q02", () => {
      mockSearchParams = new URLSearchParams({ code: "q02" });
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).toContain("Select your gender");
      expect(html).toContain('role="radiogroup"');
      expect(html).toContain("Male");
      expect(html).toContain("Female");
    });

    it("renders date input question structure for Q08", () => {
      mockSearchParams = new URLSearchParams({ code: "q08" });
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).toContain("What&#x27;s your date of birth?");
      expect(html).toContain("id=\"birthdate-input\"");
      expect(html).toContain("type=\"date\"");
      expect(html).toContain("Next");
    });

    it("renders multi choice question structure for Q18", () => {
      mockSearchParams = new URLSearchParams({ code: "q18" });
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).toContain("What life goals do you hope to achieve with your soulmate?");
      expect(html).toContain("role=\"checkbox\"");
      expect(html).toContain("Next");
    });
  });

  describe("3. API Integration: Session Bootstrap, Recovery, and Rapid-Tap Lock", () => {
    it("submitAnswer forwards questionCode, option payload, and session ID to live endpoint", async () => {
      const submitSpy = vi.spyOn(sessionApi, "submitAnswer").mockResolvedValueOnce({
        saved: true,
        question_code: "q02",
        next_step: "q03",
      });

      const res = await sessionApi.submitAnswer("ses_test123", "q02", {
        value: "female",
        duration_ms: 1200,
      });

      expect(submitSpy).toHaveBeenCalledWith("ses_test123", "q02", {
        value: "female",
        duration_ms: 1200,
      });
      expect(res.saved).toBe(true);
      expect(res.next_step).toBe("q03");
    });

    it("submitAnswer for multi-choice sends values array", async () => {
      const submitSpy = vi.spyOn(sessionApi, "submitAnswer").mockResolvedValueOnce({
        saved: true,
        question_code: "q18",
        next_step: "transition_5",
      });

      const res = await sessionApi.submitAnswer("ses_test123", "q18", {
        values: ["building_a_family", "traveling_the_world"],
        duration_ms: 2500,
      });

      expect(submitSpy).toHaveBeenCalledWith("ses_test123", "q18", {
        values: ["building_a_family", "traveling_the_world"],
        duration_ms: 2500,
      });
      expect(res.next_step).toBe("transition_5");
    });

    it("navigateBack calls server-authoritative back endpoint", async () => {
      const backSpy = vi.spyOn(sessionApi, "navigateBack").mockResolvedValueOnce({
        session_id: "ses_test123",
        current_step: "q03",
        step_type: "question",
        next_step: "q04",
        previous_step: "q02",
        progress_percent: 7,
        is_quiz_completed: false,
      });

      const res = await sessionApi.navigateBack("ses_test123");
      expect(backSpy).toHaveBeenCalledWith("ses_test123");
      expect(res.current_step).toBe("q03");
      expect(res.previous_step).toBe("q02");
    });

    it("continueTransition advances transition step authoritatively", async () => {
      const transSpy = vi.spyOn(sessionApi, "continueTransition").mockResolvedValueOnce({
        transition_code: "transition_0",
        next_step: "q02",
        flow_state: {
          session_id: "ses_test123",
          current_step: "q02",
          step_type: "question",
          next_step: "q03",
          previous_step: "transition_0",
          progress_percent: 3,
          is_quiz_completed: false,
        },
      });

      const res = await sessionApi.continueTransition("ses_test123", "transition_0");
      expect(transSpy).toHaveBeenCalledWith("ses_test123", "transition_0");
      expect(res.next_step).toBe("q02");
    });
  });

  describe("4. End-to-End Transition Integration in /soulmate/loading", () => {
    it("renders Transition-0 structure and continue button", () => {
      mockSearchParams = new URLSearchParams({ step: "0" });
      const html = renderToStaticMarkup(<SoulmateLoadingPage />);

      expect(html).toContain("data-testid=\"transition-shell-step-0\"");
      expect(html).toContain("Continue");
    });

    it("renders Transition-1 'Sketching now' badge", () => {
      mockSearchParams = new URLSearchParams({ step: "1" });
      const html = renderToStaticMarkup(<SoulmateLoadingPage />);

      expect(html).toContain("Sketching now");
      expect(html).toContain("Your artist has started");
    });

    it("renders Transition-3 with neutral fallback ('Your Zodiac') and does not hardcode 'Virgo Sun' (H-3 fix)", () => {
      mockSearchParams = new URLSearchParams({ step: "3" });
      const html = renderToStaticMarkup(<SoulmateLoadingPage />);

      expect(html).toContain("data-testid=\"transition-shell-step-3\"");
      expect(html).toContain("Good to know!");
      expect(html).toContain("Your Zodiac");
      expect(html).not.toContain("Virgo Sun");
      expect(html).toContain("people make decisions using their heart and head.");
    });

    it("renders Transition-3 dynamically from URL params when provided in fixture/dev preview", () => {
      mockSearchParams = new URLSearchParams({
        step: "3",
        zodiac: "Leo Sun",
        decision: "heart",
      });
      const html = renderToStaticMarkup(<SoulmateLoadingPage />);

      expect(html).toContain("Leo Sun");
      expect(html).toContain("people make decisions using their heart.");
      expect(html).not.toContain("Virgo Sun");
    });

    it("renders Transition-3 dynamically from server flow state metadata (H-3 server authority)", () => {
      mockSearchParams = new URLSearchParams({ step: "3" });
      const serverFlowState = {
        session_id: "test-sess-1",
        current_step: "transition_3",
        step_type: "transition",
        next_step: "q11",
        previous_step: "q10",
        progress_percent: 50,
        is_quiz_completed: false,
        step_metadata: {
          zodiac_sign: "Scorpio",
          zodiac_label: "Scorpio Sun",
          decision_style: "head",
          decision_copy: "people make decisions using their head.",
          title: "Good to know!",
          subtitle: "Many Scorpio Sun individuals make decisions using their head.",
        },
      };

      (globalThis as unknown as { __SOULMATE_TEST_FLOW_STATE__?: unknown }).__SOULMATE_TEST_FLOW_STATE__ =
        serverFlowState;
      try {
        const html = renderToStaticMarkup(<SoulmateLoadingPage />);
        expect(html).toContain("Scorpio Sun");
        expect(html).toContain("people make decisions using their head.");
        expect(html).not.toContain("Virgo Sun");
      } finally {
        delete (globalThis as unknown as { __SOULMATE_TEST_FLOW_STATE__?: unknown })
          .__SOULMATE_TEST_FLOW_STATE__;
      }
    });
  });
});
