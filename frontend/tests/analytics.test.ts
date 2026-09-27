/**
 * Central funnel analytics wrapper tests (DEV-SPEC §18, SP-901).
 *
 * Covers: §18.1 catalog completeness, §18.2 privacy redaction in code,
 * property allowlisting, sink injection, one-shot dedupe, and the two
 * §18.2 helpers (email domain bucket, server-clock hours-since-payment).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  SOULMATE_FUNNEL_EVENT_PROPERTIES,
  deriveEmailDomainType,
  hoursSincePayment,
  setSoulmateAnalyticsSink,
  trackArtifactUnlocked,
  trackOnce,
  trackSoulmateEvent,
  type SoulmateAnalyticsSink,
} from "../src/soulmate/analytics";

// The §18.1 contract, pinned literally (mirrors backend/tests/test_analytics.py).
const SPEC_181_EVENT_NAMES = [
  "soulmate_landing_view",
  "soulmate_start_click",
  "soulmate_login_click",
  "soulmate_transition_view",
  "soulmate_transition_continue",
  "soulmate_quiz_started",
  "soulmate_question_view",
  "soulmate_question_answered",
  "soulmate_quiz_back",
  "soulmate_quiz_completed",
  "soulmate_interstitial_answered",
  "soulmate_email_view",
  "soulmate_email_submitted",
  "soulmate_subscribe_view",
  "soulmate_paypal_start",
  "soulmate_paypal_approved",
  "soulmate_payment_confirmed",
  "soulmate_payment_failed",
  "soulmate_result_view",
  "soulmate_sketch_unlocked",
  "soulmate_sketch_viewed",
  "soulmate_sketch_generation_started",
  "soulmate_sketch_generation_completed",
  "soulmate_sketch_generation_failed",
  "soulmate_report_unlocked",
  "soulmate_report_viewed",
  "soulmate_subscription_cancelled",
];

function makeSink(): SoulmateAnalyticsSink & { events: { name: string; properties: Record<string, unknown> }[] } {
  const fn = Object.assign(((event) => fn.events.push(event)) as SoulmateAnalyticsSink, {
    events: [] as { name: string; properties: Record<string, unknown> }[],
  });
  return fn;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  setSoulmateAnalyticsSink(null);
  vi.resetModules();
});

describe("§18.1 event catalog", () => {
  it("declares exactly the 27 canonical DEV-SPEC §18.1 events", () => {
    expect(Object.keys(SOULMATE_FUNNEL_EVENT_PROPERTIES).sort()).toEqual(
      [...SPEC_181_EVENT_NAMES].sort()
    );
  });

  it("accepts a representative typed event for every catalog entry unchanged", () => {
    // Schema documentation by example: every event can be constructed with its
    // full declared property set and must pass through the wrapper untouched.
    const samples: Record<string, Record<string, unknown>> = {
      soulmate_landing_view: { source: "tiktok", campaign: "spring" },
      soulmate_start_click: { session_id: null },
      soulmate_login_click: { session_id: null },
      soulmate_transition_view: { step: 0 },
      soulmate_transition_continue: { step: 5 },
      soulmate_quiz_started: { quiz_version: "soulmate-quiz-v1" },
      soulmate_question_view: { question_code: "q02" },
      soulmate_question_answered: { question_code: "q08", option_codes: [], duration_ms: 4200 },
      soulmate_quiz_back: { from_q: "q05", to_q: "q04" },
      soulmate_quiz_completed: { total_duration: 190000 },
      soulmate_interstitial_answered: { code: "spiritual_person", value: true },
      soulmate_email_view: { partner_gender: "male" },
      soulmate_email_submitted: { domain_type: "gmail.com" },
      soulmate_subscribe_view: { intro_price: "19.00", regular_price: "29.00", currency: "USD" },
      soulmate_paypal_start: { plan_id: "P-123" },
      soulmate_paypal_approved: { subscription_id: "I-123" },
      soulmate_payment_confirmed: { amount: "19.00", currency: "USD" },
      soulmate_payment_failed: { reason_code: "confirmation_timeout" },
      soulmate_result_view: { sketch_availability: "LOCKED", report_availability: "LOCKED" },
      soulmate_sketch_unlocked: { session_id: "s1", hours_since_payment: 12.1 },
      soulmate_sketch_viewed: { artifact_version: null },
      soulmate_sketch_generation_started: { model: "gpt-image-2", prompt_version: "v1" },
      soulmate_sketch_generation_completed: { latency_ms: 45000, attempts: 1 },
      soulmate_sketch_generation_failed: { error_code: "GENERATION_FAILED", attempts: 3 },
      soulmate_report_unlocked: { session_id: "s1", hours_since_payment: 24.0 },
      soulmate_report_viewed: { report_version: "v1" },
      soulmate_subscription_cancelled: { provider_status: "CANCELLED" },
    };
    for (const name of SPEC_181_EVENT_NAMES) {
      const sink = makeSink();
      setSoulmateAnalyticsSink(sink);
      // Bypass typing deliberately for the pass-through check below.
      (trackSoulmateEvent as (event: { name: string; properties?: unknown }) => void)({
        name,
        properties: samples[name],
      });
      expect(sink.events.length, name).toBe(1);
      expect(sink.events[0].name).toBe(name);
      expect(sink.events[0].properties).toEqual(samples[name]);
    }
  });
});

describe("§18.2 privacy boundary", () => {
  it("strips non-catalog properties before the sink sees them", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    (trackSoulmateEvent as (event: { name: string; properties?: unknown }) => void)({
      name: "soulmate_question_answered",
      properties: { question_code: "q05", option_codes: ["asian"], raw_email: "user@example.com" },
    });
    expect(sink.events[0].properties).toEqual({ question_code: "q05", option_codes: ["asian"] });
  });

  it("redacts email-shaped and DOB-shaped string values (value-based guard)", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    (trackSoulmateEvent as (event: { name: string; properties?: unknown }) => void)({
      name: "soulmate_payment_confirmed",
      properties: { amount: "19.00", currency: "buyer@example.com" },
    });
    (trackSoulmateEvent as (event: { name: string; properties?: unknown }) => void)({
      name: "soulmate_quiz_back",
      properties: { from_q: "1995-06-15", to_q: "q04" },
    });
    expect(sink.events[0].properties).toEqual({ amount: "19.00", currency: "[redacted]" });
    expect(sink.events[1].properties).toEqual({ from_q: "[redacted]", to_q: "q04" });
  });

  it("redacts PII inside array values (option_codes defense-in-depth)", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    (trackSoulmateEvent as (event: { name: string; properties?: unknown }) => void)({
      name: "soulmate_question_answered",
      properties: { question_code: "q08", option_codes: ["user@example.com"], duration_ms: 10 },
    });
    expect(sink.events[0].properties.option_codes).toEqual(["[redacted]"]);
  });

  it("never throws on a broken sink or malformed payload", () => {
    setSoulmateAnalyticsSink(() => {
      throw new Error("sink exploded");
    });
    expect(() =>
      trackSoulmateEvent({ name: "soulmate_landing_view", properties: {} })
    ).not.toThrow();
    setSoulmateAnalyticsSink(null);
  });
});

describe("sink contract", () => {
  it("drops events when no sink is set in non-development environments", () => {
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => {});
    expect(() =>
      trackSoulmateEvent({ name: "soulmate_landing_view", properties: {} })
    ).not.toThrow();
    // NODE_ENV in vitest is "test": the default sink drops silently.
    expect(consoleInfo).not.toHaveBeenCalled();
    consoleInfo.mockRestore();
  });

  it("uses the injected sink until reset to null", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    trackSoulmateEvent({ name: "soulmate_start_click", properties: {} });
    expect(sink.events).toHaveLength(1);
    setSoulmateAnalyticsSink(null);
    trackSoulmateEvent({ name: "soulmate_start_click", properties: {} });
    expect(sink.events).toHaveLength(1);
  });

  it("logs to console in development and drops in production (default sink)", async () => {
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    vi.resetModules();
    const env = process.env as { NODE_ENV?: string };
    const previousEnv = env.NODE_ENV;
    try {
      env.NODE_ENV = "development";
      const dev = await import("../src/soulmate/analytics");
      dev.trackSoulmateEvent({ name: "soulmate_landing_view", properties: { source: "x" } });
      expect(consoleInfo).toHaveBeenCalled();

      consoleInfo.mockClear();
      vi.resetModules();
      env.NODE_ENV = "production";
      const prod = await import("../src/soulmate/analytics");
      prod.trackSoulmateEvent({ name: "soulmate_landing_view", properties: { source: "x" } });
      expect(consoleInfo).not.toHaveBeenCalled();
    } finally {
      env.NODE_ENV = previousEnv;
    }
    warn.mockRestore();
    consoleInfo.mockRestore();
  });
});

describe("one-shot + helper contract", () => {
  it("trackOnce fires once per storage key", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    const store = new Map<string, string>();
    (globalThis as unknown as { window?: unknown }).window = {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    };
    try {
      const first = trackOnce("quiz_started", { name: "soulmate_quiz_started", properties: {} });
      const second = trackOnce("quiz_started", { name: "soulmate_quiz_started", properties: {} });
      expect(first).toBe(true);
      expect(second).toBe(false);
      expect(sink.events).toHaveLength(1);
      const other = trackOnce("quiz_completed", { name: "soulmate_quiz_completed", properties: {} });
      expect(other).toBe(true);
    } finally {
      delete (globalThis as unknown as { window?: unknown }).window;
    }
  });

  it("trackArtifactUnlocked emits the §18.1 unlock event deduplicated per kind", () => {
    const sink = makeSink();
    setSoulmateAnalyticsSink(sink);
    const store = new Map<string, string>();
    (globalThis as unknown as { window?: unknown }).window = {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    };
    try {
      expect(trackArtifactUnlocked("sketch", { session_id: "s1", hours_since_payment: 12.5 })).toBe(true);
      expect(trackArtifactUnlocked("sketch", { session_id: "s1", hours_since_payment: 12.5 })).toBe(false);
      expect(trackArtifactUnlocked("report", {})).toBe(true);
      const names = sink.events.map((e) => e.name);
      expect(names).toEqual(["soulmate_sketch_unlocked", "soulmate_report_unlocked"]);
      expect(sink.events[0].properties).toEqual({ session_id: "s1", hours_since_payment: 12.5 });
    } finally {
      delete (globalThis as unknown as { window?: unknown }).window;
    }
  });

  it("deriveEmailDomainType buckets the domain, never the address", () => {
    expect(deriveEmailDomainType("User@Gmail.com")).toBe("gmail.com");
    expect(deriveEmailDomainType("a@outlook.com")).toBe("outlook.com");
    expect(deriveEmailDomainType("a@unknown-provider.io")).toBe("other");
    expect(deriveEmailDomainType("no-at-sign")).toBe("unknown");
  });

  it("hoursSincePayment derives from server timestamps only", () => {
    expect(
      hoursSincePayment("2026-09-27T12:00:00Z", "2026-09-27T00:00:00Z")
    ).toBe(12);
    expect(hoursSincePayment("2026-09-27T12:00:00Z", null)).toBeNull();
    expect(hoursSincePayment("not-a-date", "2026-09-27T00:00:00Z")).toBeNull();
    // A payment "in the future" per skew never produces negative hours.
    expect(
      hoursSincePayment("2026-09-27T00:00:00Z", "2026-09-27T12:00:00Z")
    ).toBe(0);
  });
});
