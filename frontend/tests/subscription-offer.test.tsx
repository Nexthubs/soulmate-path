/**
 * Automated tests for Subscription Offer Client API & Subscribe UI (SP-303, Decisions: PAY-01, PAY-02).
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getSubscriptionOffer, SubscriptionOfferResponse } from "../src/soulmate/api";
import SoulmateSubscribePage from "../src/app/soulmate/subscribe/page";

// Mock next/navigation
let mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

describe("SP-303: Subscription Offer Client & UI", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const mockOffer: SubscriptionOfferResponse = {
    currency: "USD",
    intro_price: "19.00",
    regular_price: "29.00",
    interval: "MONTH",
    paypal_plan_id: "P-INTRO-123",
    disclosure: {
      today_text: "Today: $19.00",
      renewal_text: "Then $29.00 / month",
      terms_text: "Automatically renews monthly until canceled. Cancel anytime.",
      interval: "MONTH",
      interval_count: 1,
      auto_renew: true,
    },
    eligibility: {
      eligible_for_intro: true,
      plan_class: "intro",
      policy: "blocked",
      is_blocked: false,
      reason: null,
    },
    paypal: {
      client_id: "client_id_xyz",
      env: "sandbox",
      plan_id: "P-INTRO-123",
    },
  };

  describe("1. getSubscriptionOffer API client", () => {
    it("fetches offer without session ID when not provided", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockOffer,
      } as Response);

      const result = await getSubscriptionOffer();
      expect(result.currency).toBe("USD");
      expect(result.intro_price).toBe("19.00");
      expect(result.disclosure.today_text).toBe("Today: $19.00");
      expect(result.disclosure.renewal_text).toBe("Then $29.00 / month");
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/subscription/offer"),
        expect.objectContaining({
          method: "GET",
          credentials: "include",
        })
      );
    });

    it("appends encoded session_id parameter when provided", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockOffer,
      } as Response);

      await getSubscriptionOffer("sess_abc_123");
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/subscription/offer?session_id=sess_abc_123"),
        expect.anything()
      );
    });

    it("throws ApiError with machine-readable code on failure", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: async () => ({
          error_code: "FORBIDDEN_OWNERSHIP",
          message: "Access forbidden",
        }),
      } as Response);

      await expect(getSubscriptionOffer("foreign_sess")).rejects.toThrow("Access forbidden");
    });
  });

  describe("2. SoulmateSubscribePage static & query binding (H-2 Remediation)", () => {
    it("renders page header and fallback without crashing", () => {
      const html = renderToStaticMarkup(<SoulmateSubscribePage />);
      expect(html).toContain("Subscription Checkout");
      expect(html).toContain("Complete Payment to Access Results");
    });

    it("H-2: disables result navigation button when unpaid and not in fixture mode", () => {
      mockSearchParams = new URLSearchParams({
        preferred_partner_gender: "female",
      });

      const html = renderToStaticMarkup(<SoulmateSubscribePage />);
      expect(html).toContain("Complete Payment to Access Results");
      expect(html).toContain("data-testid=\"subscribe-payment-pending\"");
      expect(html).not.toContain('href="/soulmate/result');
    });

    it("preserves URL query parameters on demo result navigation button in fixture mode", () => {
      mockSearchParams = new URLSearchParams({
        fixture: "true",
        preferred_partner_gender: "female",
        age_range: "age_30_40",
      });

      const html = renderToStaticMarkup(<SoulmateSubscribePage />);
      expect(html).toContain(
        'href="/soulmate/result?fixture=true&amp;preferred_partner_gender=female&amp;age_range=age_30_40"'
      );
      expect(html).toContain("[Demo Preview] Continue to Result Dashboard");
    });
  });
});
