import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ResultItemCard,
  SoulmateResultView,
  deriveCombinedUIState,
  formatCountdown,
  calculateRemainingSeconds,
  ArtifactItemState,
  ResultAggregateData,
} from "../src/soulmate/components/result";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
  }),
}));

describe("SP-106: Result Cards Fixture UI (DEV-SPEC §2, §10; DECISIONS TIME-01)", () => {
  describe("State Derivation & Matrix (DEV-SPEC §10.3)", () => {
    it("maps LOCKED with any generation state to 'countdown'", () => {
      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-23T01:00:00Z",
          availability: "LOCKED",
          generation: "NOT_STARTED",
        })
      ).toBe("countdown");

      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-23T01:00:00Z",
          availability: "LOCKED",
          generation: "COMPLETED",
        })
      ).toBe("countdown");
    });

    it("maps UNLOCKED with NOT_STARTED to 'ready'", () => {
      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-22T01:00:00Z",
          availability: "UNLOCKED",
          generation: "NOT_STARTED",
        })
      ).toBe("ready");
    });

    it("maps UNLOCKED with QUEUED or PROCESSING to 'generating'", () => {
      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-22T01:00:00Z",
          availability: "UNLOCKED",
          generation: "QUEUED",
        })
      ).toBe("generating");

      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-22T01:00:00Z",
          availability: "UNLOCKED",
          generation: "PROCESSING",
        })
      ).toBe("generating");
    });

    it("maps UNLOCKED with COMPLETED to 'completed'", () => {
      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-22T01:00:00Z",
          availability: "UNLOCKED",
          generation: "COMPLETED",
        })
      ).toBe("completed");
    });

    it("maps UNLOCKED with FAILED to 'failed'", () => {
      expect(
        deriveCombinedUIState({
          unlock_at: "2026-09-22T01:00:00Z",
          availability: "UNLOCKED",
          generation: "FAILED",
        })
      ).toBe("failed");
    });
  });

  describe("Countdown State Rendering (Figma 102:1201 & TIME-01)", () => {
    it("renders countdown card with segmented ring, timer, and hand-crafting badge", () => {
      const state: ArtifactItemState = {
        unlock_at: "2026-09-23T01:00:00Z",
        availability: "LOCKED",
        generation: "NOT_STARTED",
      };
      // Server time 11h 58m 04s prior to unlock_at (43084 seconds)
      const serverTime = "2026-09-22T13:01:56Z";

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="sketch"
          state={state}
          serverTime={serverTime}
        />
      );

      expect(html).toContain("data-testid=\"result-card-sketch\"");
      expect(html).toContain("data-ui-state=\"countdown\"");
      expect(html).toContain("data-availability=\"LOCKED\"");
      expect(html).toContain("Hint’s Astrologer is drawing a portrait of your soulmate");
      expect(html).toContain("预计完成：");
      expect(html).toContain("11:58:04");
      expect(html).toContain("✦ HAND-CRAFTING ✦");
      expect(html).toContain("stroke=\"#7c3aed\"");
    });

    it("TIME-01 Invariant: zero countdown does not unlock card if server availability is LOCKED", () => {
      // Even if time has elapsed locally or diff is 0, if server availability is still LOCKED,
      // it stays in countdown/locked UI and does not grant access.
      const state: ArtifactItemState = {
        unlock_at: "2026-09-22T12:00:00Z",
        availability: "LOCKED",
        generation: "NOT_STARTED",
      };
      const serverTime = "2026-09-22T13:00:00Z"; // Server is past target, but availability is still LOCKED

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="sketch"
          state={state}
          serverTime={serverTime}
        />
      );

      // Must remain countdown UI, not ready
      expect(html).toContain("data-ui-state=\"countdown\"");
      expect(html).toContain("00:00:00");
      expect(html).not.toContain("READY!");
      expect(html).not.toContain("Check Now");
    });
  });

  describe("Ready State Rendering (Figma 102:1332)", () => {
    it("renders ready state with glowing star icon, READY! badge, and Check Now button", () => {
      const state: ArtifactItemState = {
        unlock_at: "2026-09-22T01:00:00Z",
        availability: "UNLOCKED",
        generation: "NOT_STARTED",
      };

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="report"
          state={state}
        />
      );

      expect(html).toContain("data-testid=\"result-card-report\"");
      expect(html).toContain("data-ui-state=\"ready\"");
      expect(html).toContain("Your Soulmate Report");
      expect(html).toContain("data-testid=\"badge-ready\"");
      expect(html).toContain("READY!");
      expect(html).toContain("data-testid=\"ready-action-button\"");
      expect(html).toContain("Check Now");
    });
  });

  describe("Generating State Rendering", () => {
    it("renders loading spinner and progress bar with aria-busy", () => {
      const state: ArtifactItemState = {
        unlock_at: "2026-09-22T01:00:00Z",
        availability: "UNLOCKED",
        generation: "PROCESSING",
      };

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="sketch"
          state={state}
        />
      );

      expect(html).toContain("data-ui-state=\"generating\"");
      expect(html).toContain("aria-busy=\"true\"");
      expect(html).toContain("Drawing Your Soulmate Portrait...");
      expect(html).toContain("animate-spin");
      expect(html).toContain("animate-pulse");
    });
  });

  describe("Completed State Rendering", () => {
    it("renders completed badge, action button, and thumbnail when artifact_url is present", () => {
      const state: ArtifactItemState = {
        unlock_at: "2026-09-22T01:00:00Z",
        availability: "UNLOCKED",
        generation: "COMPLETED",
        artifact_url: "/images/email/sketch-female.png",
      };

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="sketch"
          state={state}
        />
      );

      expect(html).toContain("data-ui-state=\"completed\"");
      expect(html).toContain("Your Portrait is Ready!");
      expect(html).toContain("Completed");
      expect(html).toContain("data-testid=\"completed-action-button\"");
      expect(html).toContain("View Soulmate Sketch");
      expect(html).toContain("/images/email/sketch-female.png");
    });
  });

  describe("Failed State Rendering", () => {
    it("renders alert role, error message, and retry CTA", () => {
      const state: ArtifactItemState = {
        unlock_at: "2026-09-22T01:00:00Z",
        availability: "UNLOCKED",
        generation: "FAILED",
        error_message: "Custom upstream error occurred during generation",
      };

      const html = renderToStaticMarkup(
        <ResultItemCard
          type="report"
          state={state}
        />
      );

      expect(html).toContain("data-ui-state=\"failed\"");
      expect(html).toContain("role=\"alert\"");
      expect(html).toContain("Generation Interrupted");
      expect(html).toContain("Custom upstream error occurred during generation");
      expect(html).toContain("data-testid=\"retry-action-button\"");
      expect(html).toContain("Retry");
      expect(html).toContain("Support");
    });
  });

  describe("Full Result Screen & Aggregate API Compatibility (Acceptance #1)", () => {
    it("consumes ResultAggregateData directly matching DEV-SPEC §10.4 schema", () => {
      const aggregateData: ResultAggregateData = {
        server_time: "2026-09-22T13:00:00Z",
        subscription: {
          provider: "paypal",
          provider_status: "ACTIVE",
          first_payment_at: "2026-09-22T13:00:00Z",
          next_billing_at: "2026-10-22T13:00:00Z",
        },
        sketch: {
          unlock_at: "2026-09-23T01:00:00Z",
          availability: "LOCKED",
          generation: "NOT_STARTED",
        },
        report: {
          unlock_at: "2026-09-23T13:00:00Z",
          availability: "LOCKED",
          generation: "NOT_STARTED",
        },
      };

      const html = renderToStaticMarkup(
        <SoulmateResultView
          initialData={aggregateData}
          userEmail="user@example.com"
        />
      );

      // Verify page layout and header
      expect(html).toContain("data-testid=\"soulmate-result-view\"");
      expect(html).toContain("user@example.com");
      expect(html).toContain("Hint");
      expect(html).toContain("Your Soulmate Sketch");

      // Verify both cards rendered
      expect(html).toContain("data-testid=\"result-card-sketch\"");
      expect(html).toContain("data-testid=\"result-card-report\"");

      // Verify accelerated teaser matching Figma 102:1201 (PAY-01: no hardcoded $3.99 by default)
      expect(html).toContain("data-testid=\"accelerated-teaser\"");
      expect(html).toContain("Just 5 minutes");
      expect(html).toContain("Get an early look at");
      expect(html).toContain("Accelerated Access Coming Soon");
      expect(html).not.toContain("$3.99");
      expect(html).toContain("disabled=\"\"");

      // When acceleratedPrice is supplied via prop (e.g. from offer API)
      const htmlWithOffer = renderToStaticMarkup(
        <SoulmateResultView
          initialData={aggregateData}
          acceleratedPrice="$3.99"
        />
      );
      expect(htmlWithOffer).toContain("Proceed to Payment: ");
      expect(htmlWithOffer).toContain("$3.99");
      expect(htmlWithOffer).not.toContain("disabled=\"\"");
    });
  });

  describe("Time Formatting Helpers", () => {
    it("formatCountdown formats seconds into hh:mm:ss", () => {
      expect(formatCountdown(43084)).toBe("11:58:04");
      expect(formatCountdown(3600)).toBe("01:00:00");
      expect(formatCountdown(65)).toBe("00:01:05");
      expect(formatCountdown(0)).toBe("00:00:00");
      expect(formatCountdown(-5)).toBe("00:00:00");
    });

    it("calculateRemainingSeconds computes seconds difference between UTC timestamps", () => {
      const unlock = "2026-09-23T01:00:00Z";
      const server = "2026-09-22T13:01:56Z";
      expect(calculateRemainingSeconds(unlock, server)).toBe(43084);

      // When server is ahead of unlock
      const pastServer = "2026-09-24T00:00:00Z";
      expect(calculateRemainingSeconds(unlock, pastServer)).toBe(0);
    });
  });
});
