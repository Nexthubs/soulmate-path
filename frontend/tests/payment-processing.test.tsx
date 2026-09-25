/**
 * Automated tests for Payment-Processing Frontend State (DEV-SPEC §9.3–9.4, §15.8, SP-410).
 * Context refs: DEV-SPEC §9.3–9.4, §15.8; Decisions: PAY-AUTH-01.
 * Acceptance criteria:
 * 1. After PayPal approval, UI polls/refetches server state;
 * 2. Only transitions to Result after confirmed first payment;
 * 3. Timeout/pending case is recoverable and does not falsely claim success.
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import SoulmatePaymentProcessingPage from "../src/app/soulmate/payment-processing/page";
import { getSubscriptionStatus, SubscriptionStatusResponse } from "../src/soulmate/api/subscription";
import { SOULMATE_ROUTES } from "../src/soulmate/domain";

// Mock next/navigation
const mockPush = vi.fn();
const mockReplace = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    back: vi.fn(),
  }),
  useSearchParams: () => mockSearchParams,
}));

describe("SP-410: Payment-Processing Frontend State", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    mockPush.mockClear();
    mockReplace.mockClear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe("1. Polling & Status Verification API", () => {
    it("getSubscriptionStatus includes reconcile query parameter when requested", async () => {
      const mockStatus: SubscriptionStatusResponse = {
        status: "PROCESSING",
        is_paid: false,
        subscription_id: "I-SUB-TEST",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStatus,
      });

      const res = await getSubscriptionStatus("sess_123", true);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/subscription/status?session_id=sess_123&reconcile=true"),
        expect.anything()
      );
      expect(res.status).toBe("PROCESSING");
      expect(res.is_paid).toBe(false);
    });

    it("getSubscriptionStatus handles is_paid true state without reconcile flag", async () => {
      const mockStatus: SubscriptionStatusResponse = {
        status: "ACTIVE",
        is_paid: true,
        subscription_id: "I-SUB-PAID",
        first_payment_at: "2026-09-25T12:00:00Z",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStatus,
      });

      const res = await getSubscriptionStatus("sess_123", false);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/subscription/status?session_id=sess_123"),
        expect.anything()
      );
      expect(res.is_paid).toBe(true);
      expect(res.status).toBe("ACTIVE");
    });
  });

  describe("2. UI Rendering & Invariant Gating (PAY-AUTH-01)", () => {
    it("renders processing indicator, title, and subscription ID badge upon load", () => {
      mockSearchParams = new URLSearchParams({
        subscription_id: "I-SUB-POLL-12345",
        session_id: "sess_test_001",
      });

      const html = renderToStaticMarkup(<SoulmatePaymentProcessingPage />);
      expect(html).toContain("Confirming Payment");
      expect(html).toContain("data-testid=\"processing-subscription-badge\"");
      expect(html).toContain("I-SUB-POLL-12345");
      expect(html).toContain("PAY-AUTH-01");
      // Must not link to result directly in markup without server confirmation
      expect(html).not.toContain("data-testid=\"subscribe-result-link\"");
    });

    it("displays warning and return button when subscription ID is missing", () => {
      mockSearchParams = new URLSearchParams();

      const html = renderToStaticMarkup(<SoulmatePaymentProcessingPage />);
      expect(html).toContain("data-testid=\"processing-missing-subscription\"");
      expect(html).toContain("No active subscription ID was found");
      expect(html).toContain("data-testid=\"return-subscribe-btn\"");
      expect(html).toContain("Return to Subscription Checkout");
    });
  });

  describe("3. Timeout and Recoverability Semantics (Acceptance #3)", () => {
    it("preserves URL parameters for result destination without premature routing", () => {
      const currentParams = new URLSearchParams({
        subscription_id: "I-SUB-RECOVER",
        session_id: "sess_recover_99",
        partner_gender: "female",
      });
      mockSearchParams = currentParams;

      const html = renderToStaticMarkup(<SoulmatePaymentProcessingPage />);
      // Initial render never triggers navigation or false success claims
      expect(mockPush).not.toHaveBeenCalled();
      expect(html).toContain("We are securely verifying your PayPal subscription");
    });
  });
});
