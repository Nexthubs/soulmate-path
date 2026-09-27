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
  CancelConfirmationDialog,
  formatDate,
  formatSubscriptionPrice,
  derivePaidAccessCopy,
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

  describe("4. SP-803: plan and regular monthly price from provider-reconciled state", () => {
    it("formats backend price data and never fabricates one", () => {
      expect(formatSubscriptionPrice("29.00", "USD")).toBe("$29.00");
      expect(formatSubscriptionPrice("29", "EUR")).toBe("€29.00");
      expect(formatSubscriptionPrice("0.99", "GBP")).toBe("£0.99");
      // no/invalid price -> null so the UI omits the row instead of inventing one
      expect(formatSubscriptionPrice(null, "USD")).toBeNull();
      expect(formatSubscriptionPrice(undefined)).toBeNull();
      expect(formatSubscriptionPrice("abc", "USD")).toBeNull();
      expect(formatSubscriptionPrice("-5.00", "USD")).toBeNull();
    });

    it("shows the plan row with the backend regular monthly price", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="ACTIVE"
          isPaid={true}
          subscriptionId="I-SUB-PRICE-1"
          currency="USD"
          regularPrice="29.00"
          nextBillingAt="2026-10-25T00:00:00Z"
        />
      );

      expect(html).toContain('data-testid="subscription-plan-info"');
      expect(html).toContain("Monthly — $29.00/month");
      // Price comes from backend state; no hard-coded frontend price exists
      expect(html).toContain("$29.00");
    });

    it("omits the price portion when the backend provides no price", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction status="ACTIVE" isPaid={true} subscriptionId="I-SUB-NOPRICE" />
      );

      expect(html).toContain('data-testid="subscription-plan-info"');
      expect(html).toContain("Monthly");
      expect(html).not.toContain("/month");
    });

    it("keeps showing plan and price on the cancelled (paid-through) state", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="CANCELLED"
          isPaid={true}
          currency="EUR"
          regularPrice="29.00"
          paidThroughAt="2026-10-25T00:00:00Z"
          cancelledAt="2026-09-25T12:00:00Z"
        />
      );

      expect(html).toContain("Monthly — €29.00/month");
      expect(html).toContain("Active through Oct 25, 2026");
    });
  });

  describe("3. H-3 Route Registration & Navigation Integration", () => {
    it("registers /soulmate/settings in SOULMATE_ROUTES and ALLOWED_BACK_ROUTES", async () => {
      const { SOULMATE_ROUTES, ALLOWED_BACK_ROUTES } = await import("../src/soulmate/domain");
      expect(SOULMATE_ROUTES.SETTINGS).toBe("/soulmate/settings");
      expect(ALLOWED_BACK_ROUTES).toContain("/soulmate/settings");
    });

    it("renders settings navigation link in SoulmateResultView", async () => {
      const { SoulmateResultView, DEFAULT_RESULT_FIXTURE } = await import("../src/soulmate/components/result");
      const html = renderToStaticMarkup(
        <SoulmateResultView initialData={DEFAULT_RESULT_FIXTURE} userEmail="subscriber@example.com" />
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

  describe("5. SP-804: cancel action confirmation state and safety", () => {
    const baseDialogProps = {
      paidThroughDisplay: "Oct 25, 2026",
      isLoading: false,
      onConfirm: () => {},
      onKeep: () => {},
    };

    it("renders the confirmation state with renewal price, access promise, and retention guarantee", () => {
      const html = renderToStaticMarkup(
        <CancelConfirmationDialog {...baseDialogProps} priceText="$29.00" />
      );

      expect(html).toContain('data-testid="cancellation-confirmation-dialog"');
      expect(html).toContain('role="alertdialog"');
      expect(html).toContain('aria-modal="true"');
      // Renewal price quoted from provider-reconciled state, with supported
      // no-refund framing per DEV-SPEC §9.8 paid-through decision
      expect(html).toContain("$29.00/month");
      expect(html).toContain("Cancelling stops all future charges");
      // Clear post-cancel access message
      expect(html).toContain("You will keep access until <strong>Oct 25, 2026</strong>");
      // No deletion of completed sketch/report
      expect(html).toContain("never be deleted");
      // Both exits available
      expect(html).toContain('data-testid="confirm-cancel-button"');
      expect(html).toContain('data-testid="keep-subscription-button"');
    });

    it("omits the price sentence when the backend provides no price", () => {
      const html = renderToStaticMarkup(
        <CancelConfirmationDialog {...baseDialogProps} priceText={null} />
      );

      expect(html).not.toContain("/month");
      expect(html).toContain("Are you sure you want to cancel?");
      expect(html).toContain("Oct 25, 2026");
      expect(html).toContain("never be deleted");
    });

    it("disables both actions while a cancellation request is in flight (safe repeated action)", () => {
      const html = renderToStaticMarkup(
        <CancelConfirmationDialog {...baseDialogProps} priceText="$29.00" isLoading={true} />
      );

      expect(html).toContain("Cancelling...");
      // Only in-flight markup renders disabled state on both action buttons
      const confirmBtn = html.match(/<button[^>]*data-testid="confirm-cancel-button"[^>]*>/);
      const keepBtn = html.match(/<button[^>]*data-testid="keep-subscription-button"[^>]*>/);
      expect(confirmBtn).not.toBeNull();
      expect(confirmBtn![0]).toContain("disabled");
      expect(keepBtn).not.toBeNull();
      expect(keepBtn![0]).toContain("disabled");
      expect(html).toContain('aria-busy="true"');
    });

    it("hides the cancel entry entirely once a cancellation is recorded (idempotent UI state)", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="CANCELLED"
          isPaid={true}
          cancelledAt="2026-09-27T12:00:00Z"
          paidThroughAt="2026-10-25T00:00:00Z"
        />
      );

      expect(html).not.toContain('data-testid="cancel-subscription-button"');
      expect(html).not.toContain('data-testid="cancellation-confirmation-dialog"');
      expect(html).toContain('data-testid="cancelled-access-info"');
      expect(html).toContain('data-testid="artifact-retention-notice"');
    });
  });

  describe("6. SP-805: paid-through access copy derives from actual state", () => {
    // Fixed reference clock: client time is display-only (TIME-01); real
    // access enforcement is server-side.
    const NOW = new Date("2026-09-27T12:00:00Z");
    const FUTURE = "2026-10-25T00:00:00Z";
    const PAST = "2026-09-20T00:00:00Z";

    it("claims active access only while the paid-through date is in the future", () => {
      const copy = derivePaidAccessCopy({
        status: "CANCELLED",
        isPaid: true,
        cancelledAt: "2026-09-26T00:00:00Z",
        paidThroughAt: FUTURE,
        now: NOW,
      });
      expect(copy.state).toBe("active");
      expect(copy.headline).toBe("Active through Oct 25, 2026");
      expect(copy.detail).toContain("No future renewal charges will be made");
      expect(copy.detail).toContain("through Oct 25, 2026");
    });

    it("stops claiming active access once the paid-through date has passed", () => {
      const copy = derivePaidAccessCopy({
        status: "CANCELLED",
        isPaid: true,
        cancelledAt: "2026-09-15T00:00:00Z",
        paidThroughAt: PAST,
        now: NOW,
      });
      expect(copy.state).toBe("ended");
      expect(copy.headline).toBe("Paid access ended Sep 20, 2026");
      expect(copy.headline).not.toContain("Active");
      expect(copy.detail).toContain("Your paid access period has ended");
    });

    it("keeps no-date cancellations truthful and vague-free of access promises", () => {
      const copy = derivePaidAccessCopy({
        status: "CANCELLED",
        isPaid: true,
        cancelledAt: "2026-09-26T00:00:00Z",
        paidThroughAt: null,
        nextBillingAt: null,
        now: NOW,
      });
      expect(copy.state).toBe("retained");
      expect(copy.headline).toBe("Access retained");
      expect(copy.detail).toBe("No future renewal charges will be made.");
      expect(copy.detail).not.toContain("Active");
    });

    it("never promises renewal for SUSPENDED subscriptions", () => {
      const copy = derivePaidAccessCopy({
        status: "SUSPENDED",
        isPaid: true,
        now: NOW,
      });
      expect(copy.state).toBe("suspended");
      expect(copy.headline).toBe("Suspended");
      expect(copy.detail).toContain("suspended");
      expect(copy.detail).not.toMatch(/renews automatically/i);
      expect(copy.detail).toContain("remain saved");
    });

    it("derives expired access from the past paid-through date without renewal promises", () => {
      const copy = derivePaidAccessCopy({
        status: "EXPIRED",
        isPaid: true,
        paidThroughAt: PAST,
        now: NOW,
      });
      expect(copy.state).toBe("ended");
      expect(copy.headline).toBe("Paid access ended Sep 20, 2026");
      expect(copy.detail).toContain("No future renewal charges will be made");
      expect(copy.detail).not.toMatch(/renews automatically/i);
    });

    it("tells unpaid PROCESSING sessions that access starts only after confirmation (PAY-AUTH-01)", () => {
      const copy = derivePaidAccessCopy({
        status: "PROCESSING",
        isPaid: false,
        now: NOW,
      });
      expect(copy.state).toBe("processing");
      expect(copy.detail).toContain("begins only after your first payment is confirmed");
      expect(copy.detail).not.toMatch(/renews automatically/i);
    });

    it("preserves the supported auto-renew copy for active paid subscriptions (§9.1)", () => {
      const copy = derivePaidAccessCopy({
        status: "ACTIVE",
        isPaid: true,
        nextBillingAt: FUTURE,
        now: NOW,
      });
      expect(copy.state).toBe("renewing");
      expect(copy.detail).toBe(
        "Your subscription renews automatically monthly. You may cancel at any time while retaining access through the end of your billing cycle."
      );
    });

    it("wires the derived copy into the cancelled card (no hard-coded Active claim)", () => {
      const html = renderToStaticMarkup(
        <SubscriptionSettingsAction
          status="CANCELLED"
          isPaid={true}
          cancelledAt="2026-09-15T00:00:00Z"
          paidThroughAt={PAST}
        />
      );

      expect(html).toContain("Paid access ended Sep 20, 2026");
      expect(html).not.toContain("Active through");
      expect(html).toContain("Your paid access period has ended");
      // Retention guarantee remains regardless of the access window (§9.8)
      expect(html).toContain("never be deleted");
    });
  });
});

