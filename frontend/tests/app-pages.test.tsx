import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Import all App Router page components
import SoulmateRootPage from "../src/app/soulmate/page";
import SoulmateLoadingPage from "../src/app/soulmate/loading/page";
import SoulmateQuizPage from "../src/app/soulmate/quiz/page";
import SoulmateEmailPage from "../src/app/soulmate/email/page";
import SoulmateSubscribePage from "../src/app/soulmate/subscribe/page";
import SoulmateResultPage from "../src/app/soulmate/result/page";
import SoulmateSketchPage from "../src/app/soulmate/sketch/page";
import SoulmateReportPage from "../src/app/soulmate/report/page";
import { SOULMATE_ROUTES } from "../src/soulmate/domain";

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

describe("App Router Page-Level Behavioral Integration (M-3 Audit Remediation)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  describe("1. /soulmate (Root Landing Page)", () => {
    it("renders landing page root without error", () => {
      const html = renderToStaticMarkup(<SoulmateRootPage />);
      expect(html).toContain("Hint Soulmate");
      expect(html).toContain("See the Face");
      expect(html).toContain("Let&#x27;s begin");
    });
  });

  describe("2. /soulmate/loading (Loading & Transition Page)", () => {
    it("H-1: strictly enforces marketing compliance gate in production even with claims=true", () => {
      const originalEnv = process.env.NODE_ENV;
      try {
        (process.env as Record<string, string | undefined>).NODE_ENV = "production";
        mockSearchParams = new URLSearchParams({ step: "0", claims: "true" });

        const html = renderToStaticMarkup(<SoulmateLoadingPage />);
        expect(html).not.toContain("3 Million+ people");
        expect(html).not.toContain("Vickibeasly");
        expect(html).toContain("Astrological Guidance");
      } finally {
        (process.env as Record<string, string | undefined>).NODE_ENV = originalEnv;
      }
    });

    it("renders Transition-5 experiential progress and structure", () => {
      mockSearchParams = new URLSearchParams({ step: "5" });
      const html = renderToStaticMarkup(<SoulmateLoadingPage />);

      expect(html).toContain("Connecting to the universe");
      expect(html).toContain("See Results");
      expect(html).toContain("data-testid=\"transition-5-progress\"");
    });
  });

  describe("3. /soulmate/quiz (Quiz Page & M-1 / M-4 Gates)", () => {
    it("M-1: hides developer floating switcher toolbar in production", () => {
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

    it("M-1: shows developer floating switcher toolbar and fixture banner in dev", () => {
      mockSearchParams = new URLSearchParams({ fixture: "true" });
      const html = renderToStaticMarkup(<SoulmateQuizPage />);

      expect(html).toContain("data-testid=\"quiz-dev-toolbar\"");
      expect(html).toContain("data-testid=\"quiz-fixture-banner\"");
    });

    it("M-4: renders accessible radiogroup for single-choice questions", () => {
      const html = renderToStaticMarkup(<SoulmateQuizPage />);
      expect(html).toContain('role="radiogroup"');
      expect(html).toContain("data-testid=\"quiz-radiogroup\"");
    });
  });

  describe("4. /soulmate/email (Email Capture Page & H-3 Target)", () => {
    it("identifies sample data badge when no quiz answers are provided in URL or storage", () => {
      const html = renderToStaticMarkup(<SoulmateEmailPage />);
      expect(html).toContain("data-sample-data=\"true\"");
      expect(html).toContain("Demo Preview (No Quiz Answers Submitted)");
    });

    it("renders real quiz answer badges when query parameters are present", () => {
      mockSearchParams = new URLSearchParams({
        preferred_partner_gender: "male",
        user_gender: "female",
        age_range: "age_30_40",
        ethnicity: "asian",
      });

      const html = renderToStaticMarkup(<SoulmateEmailPage />);
      expect(html).toContain("Male");
      expect(html).toContain("30-40");
      expect(html).toContain("Asian");
      expect(html).not.toContain("data-sample-data=\"true\"");
    });
  });

  describe("5. /soulmate/subscribe (Subscribe Checkout Page & H-3 Forwarding)", () => {
    it("preserves query parameters when forwarding to Result Dashboard", () => {
      mockSearchParams = new URLSearchParams({
        preferred_partner_gender: "female",
        age_range: "age_30_40",
      });

      const html = renderToStaticMarkup(<SoulmateSubscribePage />);
      expect(html).toContain("Subscription Checkout");
      expect(html).toContain('href="/soulmate/result?preferred_partner_gender=female&amp;age_range=age_30_40"');
    });
  });

  describe("6. /soulmate/result (Result Dashboard Page & H-4 Guard)", () => {
    it("H-4: defaults to neutral user@example.com without leaking personal emails", () => {
      const html = renderToStaticMarkup(<SoulmateResultPage />);
      expect(html).toContain("user@example.com");
      expect(html).not.toContain("weijialin0827@gmail.com");
    });

    it("H-4: hides fixture toolbar in production mode", () => {
      const originalEnv = process.env.NODE_ENV;
      try {
        (process.env as Record<string, string | undefined>).NODE_ENV = "production";
        mockSearchParams = new URLSearchParams({ fixture: "true" });

        const html = renderToStaticMarkup(<SoulmateResultPage />);
        expect(html).not.toContain("data-testid=\"fixture-qa-toolbar\"");
        expect(html).not.toContain("data-testid=\"result-fixture-banner\"");
      } finally {
        (process.env as Record<string, string | undefined>).NODE_ENV = originalEnv;
      }
    });

    it("renders demo preview banner in dev mode", () => {
      const html = renderToStaticMarkup(<SoulmateResultPage />);
      expect(html).toContain("data-testid=\"result-fixture-banner\"");
    });
  });

  describe("7. /soulmate/sketch (Sketch Viewer Page & H-4 Guard)", () => {
    it("H-4: in production, state is forced to loading and cannot be spoofed to completed via URL params", () => {
      const originalEnv = process.env.NODE_ENV;
      try {
        (process.env as Record<string, string | undefined>).NODE_ENV = "production";
        mockSearchParams = new URLSearchParams({
          state: "completed",
          url: "https://attacker.com/malicious.png",
        });

        const html = renderToStaticMarkup(<SoulmateSketchPage />);
        // Must be in loading state, not completed
        expect(html).toContain("data-testid=\"sketch-loading-state\"");
        expect(html).not.toContain("https://attacker.com/malicious.png");
        expect(html).not.toContain("data-testid=\"sketch-fixture-banner\"");
      } finally {
        (process.env as Record<string, string | undefined>).NODE_ENV = originalEnv;
      }
    });

    it("in dev mode, renders fixture preview with banner", () => {
      mockSearchParams = new URLSearchParams({ fixture: "true" });
      const html = renderToStaticMarkup(<SoulmateSketchPage />);

      expect(html).toContain("data-testid=\"sketch-fixture-banner\"");
    });
  });

  describe("8. /soulmate/report (Report Page & H-4 Guard)", () => {
    it("H-4: in production, blocks unentitled direct access and renders Locked screen", () => {
      const originalEnv = process.env.NODE_ENV;
      try {
        (process.env as Record<string, string | undefined>).NODE_ENV = "production";
        mockSearchParams = new URLSearchParams({ fixture: "true" });

        const html = renderToStaticMarkup(<SoulmateReportPage />);
        expect(html).toContain("Soulmate Report Locked");
        expect(html).toContain("Return to Dashboard");
        // Must NOT render full editorial report fixture in production
        expect(html).not.toContain("data-testid=\"soulmate-report-renderer\"");
        expect(html).not.toContain("Releasing the Fear of Being Alone");
      } finally {
        (process.env as Record<string, string | undefined>).NODE_ENV = originalEnv;
      }
    });

    it("in dev mode, renders report renderer with fixture banner", () => {
      mockSearchParams = new URLSearchParams({ fixture: "true" });
      const html = renderToStaticMarkup(<SoulmateReportPage />);

      expect(html).toContain("data-testid=\"report-fixture-banner\"");
      expect(html).toContain("data-testid=\"soulmate-report-renderer\"");
      expect(html).toContain("Releasing the Fear of Being Alone");
    });
  });
});
