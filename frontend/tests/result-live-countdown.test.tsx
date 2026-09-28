/**
 * Frontend countdown using server time (SP-504, DEV-SPEC §10.4; Decisions: TIME-01, PAY-AUTH-01).
 *
 * Acceptance criteria under test:
 * 1. Countdown uses the server-time offset (client clock changes cannot alter the countdown).
 * 2. Refresh recalibrates from the server (offset recomputed from every fresh `server_time`).
 * 3. Reaching zero triggers a status refetch signal — never a local content unlock.
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ResultItemCard } from "../src/soulmate/components/result/ResultItemCard";
import {
  ArtifactItemState,
  calculateServerClockOffsetMs,
  deriveCombinedUIState,
  evaluateCountdownZeroNotification,
  getCalibratedRemainingSeconds,
  nextCountdownZeroRetry,
} from "../src/soulmate/components/result/types";
import {
  getResultAggregate,
  ResultAggregateResponse,
} from "../src/soulmate/api/result";
import { SoulmateApiError } from "../src/soulmate/api/errors";

describe("SP-504: Server-time calibrated countdown", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // ------------------------------------------------------------------
  // 1. Server clock offset math (TIME-01)
  // ------------------------------------------------------------------

  it("calculateServerClockOffsetMs returns positive offset when server clock is ahead", () => {
    const clientNow = Date.UTC(2026, 8, 26, 12, 0, 0);
    const serverTime = "2026-09-26T14:00:00Z"; // 2h ahead of client
    expect(calculateServerClockOffsetMs(serverTime, clientNow)).toBe(2 * 3600 * 1000);
  });

  it("calculateServerClockOffsetMs returns negative offset when server clock is behind", () => {
    const clientNow = Date.UTC(2026, 8, 26, 12, 0, 0);
    const serverTime = "2026-09-26T11:30:00Z"; // 30min behind client
    expect(calculateServerClockOffsetMs(serverTime, clientNow)).toBe(-30 * 60 * 1000);
  });

  it("calculateServerClockOffsetMs fails closed to 0 for missing or invalid server time", () => {
    expect(calculateServerClockOffsetMs(null, 123)).toBe(0);
    expect(calculateServerClockOffsetMs(undefined, 123)).toBe(0);
    expect(calculateServerClockOffsetMs("not-a-date", 123)).toBe(0);
  });

  it("countdown remaining is identical regardless of the client clock (server-time offset)", () => {
    // Unlock is 1h after the authoritative server 'now'
    const serverNowMs = Date.UTC(2026, 8, 26, 12, 0, 0);
    const serverTime = new Date(serverNowMs).toISOString();
    const unlockAt = new Date(serverNowMs + 3600 * 1000).toISOString();

    // Correct client clock
    const correctClientNow = serverNowMs;
    const offsetA = calculateServerClockOffsetMs(serverTime, correctClientNow);

    // Client clock runs 2h AHEAD: offset captured at fetch compensates
    const aheadClientNow = serverNowMs + 2 * 3600 * 1000;
    const offsetB = calculateServerClockOffsetMs(serverTime, aheadClientNow);

    // Client clock runs 3h BEHIND: offset captured at fetch compensates
    const behindClientNow = serverNowMs - 3 * 3600 * 1000;
    const offsetC = calculateServerClockOffsetMs(serverTime, behindClientNow);

    const remainingA = getCalibratedRemainingSeconds(unlockAt, offsetA, correctClientNow);
    const remainingB = getCalibratedRemainingSeconds(unlockAt, offsetB, aheadClientNow);
    const remainingC = getCalibratedRemainingSeconds(unlockAt, offsetC, behindClientNow);

    // All three clients observe the same server-anchored countdown (TIME-01)
    expect(remainingA).toBe(3600);
    expect(remainingB).toBe(3600);
    expect(remainingC).toBe(3600);
  });

  it("getCalibratedRemainingSeconds clamps to zero after unlock and handles null unlock_at", () => {
    const serverNowMs = Date.UTC(2026, 8, 26, 12, 0, 0);
    const offset = 0;
    const pastUnlock = new Date(serverNowMs - 60 * 1000).toISOString();
    expect(getCalibratedRemainingSeconds(pastUnlock, offset, serverNowMs)).toBe(0);
    expect(getCalibratedRemainingSeconds(null, offset, serverNowMs)).toBe(0);
    expect(getCalibratedRemainingSeconds(undefined, offset, serverNowMs)).toBe(0);
    expect(getCalibratedRemainingSeconds("garbage", offset, serverNowMs)).toBe(0);
  });

  // ------------------------------------------------------------------
  // 2. Server combined status is preferred for UI state derivation
  // ------------------------------------------------------------------

  it("deriveCombinedUIState prefers the server-derived combined status when present", () => {
    const base: ArtifactItemState = {
      unlock_at: "2026-09-22T01:00:00Z",
      availability: "UNLOCKED",
      generation: "NOT_STARTED",
    };
    expect(deriveCombinedUIState({ ...base, status: "READY" })).toBe("ready");
    expect(deriveCombinedUIState({ ...base, status: "GENERATING" })).toBe("generating");
    expect(deriveCombinedUIState({ ...base, status: "COMPLETED" })).toBe("completed");
    expect(deriveCombinedUIState({ ...base, status: "FAILED" })).toBe("failed");
    // LOCKED wins over any generation state, matching the §10.3 matrix
    expect(deriveCombinedUIState({ ...base, availability: "LOCKED", status: "LOCKED" })).toBe(
      "countdown"
    );
    // Backward compatible: items without `status` fall back to the orthogonal matrix
    expect(deriveCombinedUIState({ ...base, status: undefined })).toBe("ready");
    expect(
      deriveCombinedUIState({ ...base, availability: "LOCKED", status: undefined })
    ).toBe("countdown");
  });

  // ------------------------------------------------------------------
  // 3. Reaching zero triggers a refetch signal — never a local unlock
  // ------------------------------------------------------------------

  it("evaluateCountdownZeroNotification fires once per unlock_at while LOCKED at zero", () => {
    const unlockAt = "2026-09-26T12:00:00Z";

    // First observation at zero -> notify
    let decision = evaluateCountdownZeroNotification("countdown", 0, unlockAt, null);
    expect(decision).toEqual({ notify: true, nextLastNotifiedUnlock: unlockAt });

    // Subsequent renders at zero for the SAME unlock -> no duplicate notifications
    decision = evaluateCountdownZeroNotification("countdown", 0, unlockAt, unlockAt);
    expect(decision).toEqual({ notify: false, nextLastNotifiedUnlock: unlockAt });

    // New unlock_at from a refetch -> notify again for the new target
    const newUnlockAt = "2026-09-27T12:00:00Z";
    decision = evaluateCountdownZeroNotification("countdown", 0, newUnlockAt, unlockAt);
    expect(decision).toEqual({ notify: true, nextLastNotifiedUnlock: newUnlockAt });
  });

  it("evaluateCountdownZeroNotification resets the guard once time remains again", () => {
    const unlockAt = "2026-09-26T12:00:00Z";
    // Refetch returned a later unlock so time remains -> guard resets
    const decision = evaluateCountdownZeroNotification("countdown", 120, unlockAt, unlockAt);
    expect(decision).toEqual({ notify: false, nextLastNotifiedUnlock: null });
  });

  it("evaluateCountdownZeroNotification never notifies for unlocked cards or missing unlock_at", () => {
    expect(
      evaluateCountdownZeroNotification("ready", 0, "2026-09-26T12:00:00Z", null).notify
    ).toBe(false);
    expect(evaluateCountdownZeroNotification("countdown", 0, null, null).notify).toBe(false);
    expect(evaluateCountdownZeroNotification("countdown", 0, undefined, null).notify).toBe(false);
  });

  // ------------------------------------------------------------------
  // 4. Card rendering with the calibrated offset
  // ------------------------------------------------------------------

  it("card renders a live calibrated countdown from the clockOffsetMs prop", () => {
    // Anchor everything to the real fetch instant so the test has no fixed-date dependency.
    const fetchClientNowMs = Date.now();
    const serverTime = new Date(fetchClientNowMs + 30 * 60 * 1000).toISOString(); // server 30min ahead
    const unlockAt = new Date(fetchClientNowMs + 2 * 3600 * 1000).toISOString(); // 2h after fetch
    const offsetMs = calculateServerClockOffsetMs(serverTime, fetchClientNowMs);

    const state: ArtifactItemState = {
      unlock_at: unlockAt,
      availability: "LOCKED",
      generation: "NOT_STARTED",
      status: "LOCKED",
    };

    const html = renderToStaticMarkup(
      <ResultItemCard type="sketch" state={state} clockOffsetMs={offsetMs} />
    );

    expect(html).toContain('data-ui-state="countdown"');
    // A multi-hour countdown must be displayed, not the zero state
    expect(html).toMatch(/\d{2}:\d{2}:\d{2}/);
    expect(html).not.toContain("00:00:00");
  });

  it("TIME-01: countdown calibrated past zero stays LOCKED and shows 00:00:00 (no local unlock)", () => {
    // Server clock is 2h ahead of the client; unlock already passed in server time.
    const fetchClientNowMs = Date.now();
    const serverTime = new Date(fetchClientNowMs + 2 * 3600 * 1000).toISOString();
    const unlockAt = new Date(fetchClientNowMs + 1 * 3600 * 1000).toISOString(); // 1h before server now
    const offsetMs = calculateServerClockOffsetMs(serverTime, fetchClientNowMs);

    const state: ArtifactItemState = {
      unlock_at: unlockAt,
      availability: "LOCKED",
      generation: "NOT_STARTED",
      status: "LOCKED",
    };

    const html = renderToStaticMarkup(
      <ResultItemCard type="sketch" state={state} clockOffsetMs={offsetMs} />
    );

    expect(html).toContain('data-ui-state="countdown"');
    expect(html).toContain('data-availability="LOCKED"');
    expect(html).toContain("00:00:00");
    expect(html).not.toContain('data-ui-state="ready"');
  });

  it("card renders the zero countdown safely when the server reports a missing unlock_at", () => {
    const state: ArtifactItemState = {
      unlock_at: null,
      availability: "LOCKED",
      generation: "NOT_STARTED",
      status: "LOCKED",
    };

    const html = renderToStaticMarkup(
      <ResultItemCard type="report" state={state} clockOffsetMs={0} />
    );
    expect(html).toContain('data-ui-state="countdown"');
    expect(html).toContain("00:00:00");
  });

  // ------------------------------------------------------------------
  // 5. Result aggregate API client (single authority call)
  // ------------------------------------------------------------------

  it("getResultAggregate requests /result with credentials and parses the aggregate", async () => {
    const mockResponse: ResultAggregateResponse = {
      session_id: "session-test",
      server_time: "2026-09-26T12:00:00Z",
      subscription: {
        provider: "paypal",
        provider_status: "ACTIVE",
        first_payment_at: "2026-09-26T11:00:00Z",
        next_billing_at: "2026-10-26T11:00:00Z",
      },
      sketch: {
        unlock_at: "2026-09-26T23:00:00Z",
        availability: "LOCKED",
        generation: "NOT_STARTED",
        status: "LOCKED",
      },
      report: {
        unlock_at: "2026-09-27T11:00:00Z",
        availability: "LOCKED",
        generation: "NOT_STARTED",
        status: "LOCKED",
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const data = await getResultAggregate("sess_504");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/result?session_id=sess_504"),
      expect.objectContaining({ credentials: "include" })
    );
    expect(data.server_time).toBe("2026-09-26T12:00:00Z");
    expect(data.sketch.status).toBe("LOCKED");
    expect(data.subscription?.provider).toBe("paypal");
  });

  it("getResultAggregate surfaces 403 as FORBIDDEN_OWNERSHIP for unentitled callers", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        error_code: "FORBIDDEN_OWNERSHIP",
        message: "Result is available only after a confirmed first payment (PAY-AUTH-01).",
      }),
    });

    await expect(getResultAggregate()).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(SoulmateApiError);
      const apiErr = err as SoulmateApiError;
      expect(apiErr.status).toBe(403);
      expect(apiErr.errorCode).toBe("FORBIDDEN_OWNERSHIP");
      return true;
    });
  });
});

describe("RV round-2: countdown zero handling and retry affordances", () => {
  it("rounds positive sub-second remaining UP so zero means truly unlocked", () => {
    const serverNowMs = Date.UTC(2026, 8, 26, 12, 0, 0);
    const offset = 0;
    // 400ms before unlock: floor would say 0 (early zero); ceil correctly says 1
    const almostUnlock = new Date(serverNowMs + 400).toISOString();
    expect(getCalibratedRemainingSeconds(almostUnlock, offset, serverNowMs)).toBe(1);
    // Exactly at the unlock instant -> 0
    const atUnlock = new Date(serverNowMs).toISOString();
    expect(getCalibratedRemainingSeconds(atUnlock, offset, serverNowMs)).toBe(0);
  });

  it("nextCountdownZeroRetry bounds automatic retries per unlock_at", () => {
    const unlockAt = "2026-09-26T12:00:00Z";
    const other = "2026-09-27T12:00:00Z";
    // No prior state -> first attempt
    expect(nextCountdownZeroRetry(null, unlockAt)).toBe(1);
    // Attempts grow until the bound
    expect(nextCountdownZeroRetry({ unlockAt, attempts: 1 }, unlockAt)).toBe(2);
    expect(nextCountdownZeroRetry({ unlockAt, attempts: 2 }, unlockAt)).toBe(3);
    expect(nextCountdownZeroRetry({ unlockAt, attempts: 3 }, unlockAt)).toBeNull();
    expect(
      nextCountdownZeroRetry({ unlockAt, attempts: 3 }, unlockAt, 5)
    ).toBe(4);
    // A NEW unlock (e.g. corrected base) restarts the bounded chain
    expect(nextCountdownZeroRetry({ unlockAt, attempts: 3 }, other)).toBe(1);
  });

  it("failed-state Retry renders disabled with Support entry when no formal handler exists", () => {
    const state: ArtifactItemState = {
      unlock_at: "2026-09-22T01:00:00Z",
      availability: "UNLOCKED",
      generation: "FAILED",
      status: "FAILED",
      error_message: "Generation failed.",
    };

    const disabledHtml = renderToStaticMarkup(
      <ResultItemCard type="sketch" state={state} retryDisabled />
    );
    expect(disabledHtml).toContain('data-testid="retry-action-button"');
    expect(disabledHtml).toContain("disabled");
    expect(disabledHtml).toContain("Support");

    const enabledHtml = renderToStaticMarkup(
      <ResultItemCard
        type="sketch"
        state={state}
        retryDisabled={false}
        onRetry={() => {}}
      />
    );
    expect(enabledHtml).toContain('data-testid="retry-action-button"');
    expect(enabledHtml).not.toContain("disabled");
  });
});

describe("RV round-3: support entry replaces the dead anchor", () => {
  const failedState: ArtifactItemState = {
    unlock_at: "2026-09-22T01:00:00Z",
    availability: "UNLOCKED",
    generation: "FAILED",
    status: "FAILED",
    error_message: "Generation failed.",
  };

  it("renders an in-product support toggle (no dead #support anchor) when no support URL is configured", () => {
    const html = renderToStaticMarkup(
      <ResultItemCard type="sketch" state={failedState} supportUrl="" retryDisabled />
    );
    expect(html).toContain('data-testid="support-toggle-button"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('href="#support"');
  });

  it("renders a real external support link when a support URL is configured", () => {
    const html = renderToStaticMarkup(
      <ResultItemCard
        type="sketch"
        state={failedState}
        supportUrl="mailto:support@example.com"
        retryDisabled
      />
    );
    expect(html).toContain('data-testid="support-link-button"');
    expect(html).toContain('href="mailto:support@example.com"');
    expect(html).not.toContain('href="#support"');
    expect(html).not.toContain('data-testid="support-toggle-button"');
  });
});
