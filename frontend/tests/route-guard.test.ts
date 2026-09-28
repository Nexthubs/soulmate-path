/**
 * Automated tests for Route Guard API Client & Logic (SP-304, DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { checkRouteGuard, RouteGuardResponse } from "../src/soulmate/api";
import {
  resolveGuardFailurePolicy,
  HIGH_VALUE_ROUTES,
} from "../src/soulmate/hooks/useRouteGuard";

describe("SP-304: Route Guard Client API & Fail-Closed Guard Policy", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const mockAllowedVerdict: RouteGuardResponse = {
    allowed: true,
    target_route: "/soulmate/email",
    redirect_to: null,
    reason: null,
    server_time: "2026-09-24T12:00:00Z",
    session_id: "sess_test_123",
    quiz_completed: true,
    email_captured: false,
    is_paid: false,
    sketch_unlocked: false,
    report_unlocked: false,
  };

  const mockBlockedVerdict: RouteGuardResponse = {
    allowed: false,
    target_route: "/soulmate/result",
    redirect_to: "/soulmate/subscribe",
    reason: "First payment must be confirmed to access result dashboard.",
    server_time: "2026-09-24T12:00:00Z",
    session_id: "sess_test_123",
    quiz_completed: true,
    email_captured: true,
    is_paid: false,
    sketch_unlocked: false,
    report_unlocked: false,
  };

  it("calls /guard/check with target_route parameter", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockAllowedVerdict,
    } as Response);

    const res = await checkRouteGuard("/soulmate/email");
    expect(res.allowed).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/guard/check?target_route=%2Fsoulmate%2Femail"),
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
  });

  it("appends session_id when provided", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockBlockedVerdict,
    } as Response);

    const res = await checkRouteGuard("/soulmate/result", "sess_custom_abc");
    expect(res.allowed).toBe(false);
    expect(res.redirect_to).toBe("/soulmate/subscribe");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("target_route=%2Fsoulmate%2Fresult&session_id=sess_custom_abc"),
      expect.anything()
    );
  });

  it("correctly parses 403 ForbiddenOwnershipError (IDOR guard)", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        error_code: "FORBIDDEN_OWNERSHIP",
        message: "Access to the requested session is forbidden.",
      }),
    } as Response);

    await expect(checkRouteGuard("/soulmate/result", "foreign_id")).rejects.toThrow(
      "Access to the requested session is forbidden."
    );
  });

  it("accurately reports server unlock status per TIME-01 and PAY-AUTH-01", async () => {
    const mockSketchUnlocked: RouteGuardResponse = {
      allowed: true,
      target_route: "/soulmate/sketch",
      redirect_to: null,
      reason: null,
      server_time: "2026-09-25T01:00:00Z",
      session_id: "sess_paid_123",
      quiz_completed: true,
      email_captured: true,
      is_paid: true,
      sketch_unlocked: true,
      report_unlocked: false,
      sketch_unlock_at: "2026-09-25T00:00:00Z",
      report_unlock_at: "2026-09-25T12:00:00Z",
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockSketchUnlocked,
    } as Response);

    const res = await checkRouteGuard("/soulmate/sketch");
    expect(res.allowed).toBe(true);
    expect(res.is_paid).toBe(true);
    expect(res.sketch_unlocked).toBe(true);
    expect(res.report_unlocked).toBe(false);
  });

  describe("Fail-Closed Security Policy (C-1 Audit Remediation, PAY-AUTH-01)", () => {
    it("strictly fails closed for high-value paid routes (/result, /sketch, /report) by default", () => {
      expect(resolveGuardFailurePolicy("/soulmate/result")).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(resolveGuardFailurePolicy("/soulmate/sketch")).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(resolveGuardFailurePolicy("/soulmate/report")).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(HIGH_VALUE_ROUTES).toContain("/soulmate/result");
      expect(HIGH_VALUE_ROUTES).toContain("/soulmate/sketch");
      expect(HIGH_VALUE_ROUTES).toContain("/soulmate/report");
    });

    it("prevents bypassing fail-closed on high-value routes even if failClosed=false is passed", () => {
      // High-risk invariant (PAY-AUTH-01): caller cannot compromise high-value paid routes
      expect(resolveGuardFailurePolicy("/soulmate/result", { failClosed: false })).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(resolveGuardFailurePolicy("/soulmate/sketch", { failClosed: false })).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(resolveGuardFailurePolicy("/soulmate/report", { failClosed: false })).toEqual({
        allowed: false,
        shouldBlock: true,
      });
    });

    it("defaults to fail-closed on onboarding routes but allows graceful fail-open when configured", () => {
      expect(resolveGuardFailurePolicy("/soulmate/email")).toEqual({
        allowed: false,
        shouldBlock: true,
      });
      expect(resolveGuardFailurePolicy("/soulmate/subscribe")).toEqual({
        allowed: false,
        shouldBlock: true,
      });

      // When gracefully allowed for onboarding routes:
      expect(resolveGuardFailurePolicy("/soulmate/email", { failClosed: false })).toEqual({
        allowed: true,
        shouldBlock: false,
      });
      expect(resolveGuardFailurePolicy("/soulmate/subscribe", { failClosed: false })).toEqual({
        allowed: true,
        shouldBlock: false,
      });
    });

    it("rejects network failure / 500 when calling checkRouteGuard and resolves to fail-closed", async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error("Network connection lost"));

      await expect(checkRouteGuard("/soulmate/result")).rejects.toThrow("Network connection lost");
      const policy = resolveGuardFailurePolicy("/soulmate/result");
      expect(policy.allowed).toBe(false);
      expect(policy.shouldBlock).toBe(true);
    });
  });
});
