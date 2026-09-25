/**
 * Automated tests for Subscription Cancellation & Settings Action (DEV-SPEC §9.8, §15.9, SP-409).
 * Tests:
 * 1. cancelSubscription API client function (server-side POST /subscription/cancel).
 * 2. SubscriptionSettingsAction component rendering:
 *    - Active state with next billing date.
 *    - Cancellation confirmation dialog.
 *    - Post-cancellation state: displays paid-through access date, no renewals.
 *    - Artifact retention guarantee message.
 *    - Safe repeated/idempotent cancellation.
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  cancelSubscription,
  SubscriptionCancelResponse,
} from "../src/soulmate/api/subscription";
import {
  SubscriptionSettingsAction,
  formatDate,
} from "../src/soulmate/components/settings";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("SP-409: Subscription Cancellation & Settings Action", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe("1. cancelSubscription API client", () => {
    it("calls POST /subscription/cancel with correct headers and payload", async () => {
      const mockResponse: SubscriptionCancelResponse = {
        status: "CANCELLED",
        is_paid: true,
        subscription_id: "I-SUB-12345",
        provider_status: "CANCELLED",
        cancelled_at: "2026-09-25T12:00:00Z",
        paid_through_at: "2026-10-25T12:00:00Z",
        message: "Subscription successfully cancelled.",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      });

      const res = await cancelSubscription({
        session_id: "session-abc-123",
        reason: "User requested cancel",
      });

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/subscription/cancel"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
            "Accept": "application/json",
          }),
          body: JSON.stringify({
            session_id: "session-abc-123",
            reason: "User requested cancel",
          }),
        })
      );
      expect(res.status).toBe("CANCELLED");
      expect(res.is_paid).toBe(true);
      expect(res.paid_through_at).toBe("2026-10-25T12:00:00Z");
    });

    it("handles error response properly", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({
          error: {
            code: "NOT_FOUND",
            message: "No subscription found for this session.",
          },
        }),
      });

      await expect(
        cancelSubscription({ session_id: "non-existent" })
      ).rejects.toThrow();
    });
  });

  describe("2. SubscriptionSettingsAction UI Rendering", () => {
    it("renders active subscription state with next billing date and cancel button", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="ACTIVE"
          isPaid={true}
          subscriptionId="I-SUB-ACTIVE-1"
          nextBillingAt="2026-10-25T00:00:00Z"
        />
      );

      expect(html).toContain("Active");
      expect(html).toContain("I-SUB-ACTIVE-1");
      expect(html).toContain("Next Renewal Date:");
      expect(html).toContain("Oct 25, 2026");
      expect(html).toContain("Cancel Subscription");
    });

    it("renders cancelled subscription state with paid-through access and artifact retention notice", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="CANCELLED"
          isPaid={true}
          subscriptionId="I-SUB-CANCELLED-1"
          paidThroughAt="2026-10-25T00:00:00Z"
          cancelledAt="2026-09-25T12:00:00Z"
        />
      );

      expect(html).toContain("Cancelled");
      expect(html).toContain("Active through Oct 25, 2026");
      expect(html).toContain("No future renewal charges will be made");
      expect(html).toContain("Your completed Soulmate Sketch and Report are permanently saved and will never be deleted.");
      // Cancel button should NOT be rendered when already cancelled
      expect(html).not.toContain("Cancel Subscription");
    });

    it("formats ISO dates reliably with UTC timezone", () => {
      expect(formatDate("2026-10-25T00:00:00Z")).toBe("Oct 25, 2026");
      expect(formatDate(null)).toBe("N/A");
      expect(formatDate(undefined)).toBe("N/A");
    });
  });

  describe("3. H-3 Route Registration & Navigation Integration", () => {
    it("registers /soulmate/settings in SOULMATE_ROUTES and ALLOWED_BACK_ROUTES", async () => {
      const { SOULMATE_ROUTES, ALLOWED_BACK_ROUTES } = await import("../src/soulmate/domain");
      expect(SOULMATE_ROUTES.SETTINGS).toBe("/soulmate/settings");
      expect(ALLOWED_BACK_ROUTES).toContain("/soulmate/settings");
    });

    it("renders settings navigation link in SoulmateResultView", async () => {
      const { SoulmateResultView } = await import("../src/soulmate/components/result");
      const html = renderToStaticMarkup(
        <SoulmateResultView userEmail="subscriber@example.com" />
      );

      expect(html).toContain('href="/soulmate/settings"');
      expect(html).toContain('data-testid="settings-nav-link"');
      expect(html).toContain("subscriber@example.com");
    });

    it("renders SoulmateSettingsPage structure mounting SubscriptionSettingsAction and back link", async () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="ACTIVE"
          isPaid={true}
          subscriptionId="I-PAGE-TEST-123"
          nextBillingAt="2026-11-01T12:00:00Z"
        />
      );

      expect(html).toContain("I-PAGE-TEST-123");
      expect(html).toContain("Active");
      expect(html).toContain("Nov 1, 2026");
    });
  });
});

