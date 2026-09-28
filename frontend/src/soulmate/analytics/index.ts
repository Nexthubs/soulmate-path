/**
 * Central funnel analytics wrapper (DEV-SPEC §18, SP-901).
 *
 * Single contract for every §18.1 funnel event on both the property and naming
 * level: event names and their allowed properties are declared here once, and
 * `trackSoulmateEvent` is the ONLY way UI code emits an analytics event.
 *
 * Privacy contract (DEV-SPEC §18.2, enforced in code, not by convention):
 * - The event catalog below is an allowlist. Properties outside the declared
 *   schema for an event are stripped before the sink sees them.
 * - Any string property value that is email-shaped or a raw calendar date
 *   (DOB-shaped) is replaced with "[redacted]" — raw email/DOB/full answers
 *   must never reach an analytics sink.
 * - Free-text answers never appear in the catalog at all: quiz answers are
 *   tracked as option codes only.
 *
 * Transport: the sink is pluggable (`setSoulmateAnalyticsSink`) so a provider
 * can be wired later without touching instrumented pages. The default sink
 * logs to the console in development and drops events elsewhere — no
 * third-party analytics provider has been approved yet (production sink is an
 * open M6 decision), and dropping is the privacy-safe default.
 *
 * Every tracking call is best-effort: analytics must never break the funnel.
 */

/** Runtime environment used to pick the default sink. */
const ENV = typeof process !== "undefined" ? process.env?.NODE_ENV : undefined;

/**
 * The canonical §18.1 event catalog: every event with its allowed property
 * names. This table IS the documented event schema for the codebase; the
 * DEV-SPEC §18.1 table remains the product contract it mirrors.
 */
export const SOULMATE_FUNNEL_EVENT_PROPERTIES = {
  soulmate_landing_view: ["source", "campaign"],
  soulmate_start_click: ["session_id"],
  soulmate_login_click: ["session_id"],
  soulmate_transition_view: ["step"],
  soulmate_transition_continue: ["step"],
  soulmate_quiz_started: ["quiz_version"],
  soulmate_question_view: ["question_code"],
  soulmate_question_answered: ["question_code", "option_codes", "duration_ms"],
  soulmate_quiz_back: ["from_q", "to_q"],
  soulmate_quiz_completed: ["total_duration"],
  soulmate_interstitial_answered: ["code", "value"],
  soulmate_email_view: ["partner_gender"],
  soulmate_email_submitted: ["domain_type"],
  soulmate_subscribe_view: ["intro_price", "regular_price", "currency"],
  soulmate_paypal_start: ["plan_id"],
  soulmate_paypal_approved: ["subscription_id"],
  soulmate_payment_confirmed: ["amount", "currency"],
  soulmate_payment_failed: ["reason_code"],
  soulmate_result_view: ["sketch_availability", "report_availability"],
  soulmate_sketch_unlocked: ["session_id", "hours_since_payment"],
  soulmate_sketch_viewed: ["artifact_version"],
  soulmate_sketch_generation_started: ["model", "prompt_version"],
  soulmate_sketch_generation_completed: ["latency_ms", "attempts"],
  soulmate_sketch_generation_failed: ["error_code", "attempts"],
  soulmate_report_unlocked: ["session_id", "hours_since_payment"],
  soulmate_report_viewed: ["report_version"],
  soulmate_subscription_cancelled: ["provider_status"],
} as const;

export type SoulmateFunnelEventName = keyof typeof SOULMATE_FUNNEL_EVENT_PROPERTIES;

/** Property contract per event (compile-time mirror of the catalog above). */
export interface SoulmateFunnelEventMap {
  soulmate_landing_view: { source?: string; campaign?: string };
  soulmate_start_click: { session_id?: string | null };
  soulmate_login_click: { session_id?: string | null };
  soulmate_transition_view: { step: number };
  soulmate_transition_continue: { step: number };
  soulmate_quiz_started: { quiz_version?: string | null };
  soulmate_question_view: { question_code: string };
  soulmate_question_answered: { question_code: string; option_codes: string[]; duration_ms: number | null };
  soulmate_quiz_back: { from_q: string; to_q: string | null };
  soulmate_quiz_completed: { total_duration: number | null };
  soulmate_interstitial_answered: { code: string; value: boolean | string };
  soulmate_email_view: { partner_gender?: string | null };
  soulmate_email_submitted: { domain_type: string };
  soulmate_subscribe_view: { intro_price?: string | null; regular_price?: string | null; currency?: string | null };
  soulmate_paypal_start: { plan_id?: string | null };
  soulmate_paypal_approved: { subscription_id?: string | null };
  soulmate_payment_confirmed: { amount?: string | null; currency?: string | null };
  soulmate_payment_failed: { reason_code: string };
  soulmate_result_view: { sketch_availability: string; report_availability: string };
  soulmate_sketch_unlocked: { session_id?: string | null; hours_since_payment?: number | null };
  soulmate_sketch_viewed: { artifact_version: string };
  soulmate_sketch_generation_started: { model?: string | null; prompt_version?: string | null };
  soulmate_sketch_generation_completed: { latency_ms?: number | null; attempts?: number | null };
  soulmate_sketch_generation_failed: { error_code: string; attempts?: number | null };
  soulmate_report_unlocked: { session_id?: string | null; hours_since_payment?: number | null };
  soulmate_report_viewed: { report_version?: string | null };
  soulmate_subscription_cancelled: { provider_status?: string | null };
}

/** A typed, sink-ready funnel event. */
export interface SoulmateFunnelEvent<K extends SoulmateFunnelEventName = SoulmateFunnelEventName> {
  name: K;
  properties: SoulmateFunnelEventMap[K];
}

/** Sink receives sanitized (allowlisted, PII-redacted) events only. */
export type SoulmateAnalyticsSink = (event: {
  name: SoulmateFunnelEventName;
  properties: Record<string, unknown>;
}) => void;

let activeSink: SoulmateAnalyticsSink | null = null;

function defaultSink(): SoulmateAnalyticsSink | null {
  if (ENV === "development") {
    return (event) => {
      // Dev visibility only; never a production transport.
      console.info("[soulmate:analytics]", event.name, event.properties);
    };
  }
  // No approved third-party analytics provider yet: drop in
  // production/test rather than leak funnel data to console or network.
  return null;
}

/**
 * Replace the active sink (tests, or a future approved provider adapter).
 * Passing null restores the default sink.
 */
export function setSoulmateAnalyticsSink(sink: SoulmateAnalyticsSink | null): void {
  activeSink = sink;
}

function resolveSink(): SoulmateAnalyticsSink | null {
  return activeSink ?? defaultSink();
}

/** Match email-shaped substrings too, since attribution values are untrusted free text. */
const EMAIL_LIKE = /[\p{L}\p{M}\p{N}.!#$%&'*+/=?^_`{|}~-]+@[\p{L}\p{M}\p{N}](?:[\p{L}\p{M}\p{N}-]{0,61}[\p{L}\p{M}\p{N}])?(?:\.[\p{L}\p{M}\p{N}](?:[\p{L}\p{M}\p{N}-]{0,61}[\p{L}\p{M}\p{N}])?)+/giu;
/** Calendar-date-shaped strings (DOB values); broad on purpose and not start-anchored. */
const DATE_LIKE = /\b\d{4}-\d{2}-\d{2}\b/g;

/** §18.2 defense-in-depth: redact email/DOB-shaped string values. */
function redactPIIValue(value: unknown): unknown {
  if (typeof value === "string") {
    return value.replace(EMAIL_LIKE, "[redacted]").replace(DATE_LIKE, "[redacted]");
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactPIIValue(item));
  }
  return value;
}

/**
 * Emit one funnel event through the central wrapper. Properties are filtered
 * to the event's catalog allowlist and PII-redacted before reaching the sink.
 * Never throws: a broken sink or bad payload must not break the user flow.
 */
export function trackSoulmateEvent<K extends SoulmateFunnelEventName>(
  event: SoulmateFunnelEvent<K>
): void {
  try {
    const allowed = SOULMATE_FUNNEL_EVENT_PROPERTIES[event.name] as readonly string[];
    const sanitized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(event.properties ?? {})) {
      if (!allowed.includes(key)) {
        if (ENV === "development") {
          console.warn(`[soulmate:analytics] dropped non-catalog property "${key}" on ${event.name}`);
        }
        continue;
      }
      if (value === undefined) continue;
      sanitized[key] = redactPIIValue(value);
    }
    const sink = resolveSink();
    if (sink) {
      sink({ name: event.name, properties: sanitized });
    }
  } catch {
    // Analytics is best-effort by contract; swallow everything.
  }
}

function onceStorageKey(key: string): string {
  return `soulmate_analytics_once_${key}`;
}

/**
 * Emit a session-level one-shot event (quiz_started, quiz_completed,
 * artifact unlocks). Returns true only when this call actually fired.
 */
export function trackOnce(key: string, event: SoulmateFunnelEvent): boolean {
  try {
    const storageKey = onceStorageKey(key);
    if (typeof window !== "undefined" && window.sessionStorage?.getItem(storageKey)) {
      return false;
    }
    trackSoulmateEvent(event);
    if (typeof window !== "undefined" && window.sessionStorage) {
      try {
        window.sessionStorage.setItem(storageKey, "1");
      } catch {
        // Storage restricted: the event already fired; a tab-session repeat is acceptable.
      }
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Track a Result/Sketch/Report view once per authorized session during the
 * caller's component mount. The caller owns this Set in a useRef, so leaving
 * and reopening the page starts a fresh view. Missing IDs suppress the event.
 */
export function trackSessionViewOnce<K extends SoulmateFunnelEventName>(
  trackedViewKeys: Set<string>,
  event: SoulmateFunnelEvent<K>,
  sessionId?: string | null
): boolean {
  const stableSessionId = typeof sessionId === "string" ? sessionId.trim() : "";
  if (!stableSessionId) return false;
  const key = `${event.name}:${encodeURIComponent(stableSessionId)}`;
  if (trackedViewKeys.has(key)) return false;
  trackedViewKeys.add(key);
  trackSoulmateEvent(event);
  return true;
}

/**
 * First unlocked view of an artifact (§18.1 `soulmate_sketch_unlocked` /
 * `soulmate_report_unlocked`). Deduplicated per tab session across the Result
 * dashboard and the artifact pages, whichever renders the unlocked state first.
 */
export function trackArtifactUnlocked(
  kind: "sketch" | "report",
  properties: SoulmateFunnelEventMap["soulmate_sketch_unlocked"]
): boolean {
  const name: SoulmateFunnelEventName =
    kind === "sketch" ? "soulmate_sketch_unlocked" : "soulmate_report_unlocked";
  const event = { name, properties } as SoulmateFunnelEvent;
  const sessionId = typeof properties.session_id === "string" ? properties.session_id.trim() : "";
  if (!sessionId) {
    // A stable session identity is required for safe deduplication. Authenticated
    // status APIs return it even when the caller authenticated by cookie alone.
    return false;
  }
  return trackOnce(
    `${kind}_unlocked:${encodeURIComponent(sessionId)}`,
    event
  );
}

export interface ResultArtifactUnlockInput {
  sessionId?: string;
  sketchAvailability: string;
  reportAvailability: string;
  serverTime?: string | null;
  firstPaymentAt?: string | null;
}

/**
 * Track unlocks from every fresh server Result aggregate. Call this even when
 * a previous aggregate was LOCKED: countdown expiry only refetches, and the
 * server response is the authority that changes availability.
 */
export function trackResultArtifactUnlocks(input: ResultArtifactUnlockInput): void {
  const properties = {
    session_id: input.sessionId,
    hours_since_payment: hoursSincePayment(input.serverTime, input.firstPaymentAt),
  };
  if (input.sketchAvailability === "UNLOCKED") {
    trackArtifactUnlocked("sketch", properties);
  }
  if (input.reportAvailability === "UNLOCKED") {
    trackArtifactUnlocked("report", properties);
  }
}

/**
 * §18.1 `soulmate_email_submitted` carries the email DOMAIN BUCKET only —
 * never the raw address (§18.2). Unrecognized domains collapse to "other".
 */
export function deriveEmailDomainType(email: string): string {
  const domain = email.split("@")[1]?.trim().toLowerCase() ?? "";
  if (!domain) return "unknown";
  const knownDomains = [
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
  ];
  return knownDomains.includes(domain) ? domain : "other";
}

/**
 * Hours between the first completed payment and the server-observed unlock,
 * derived from SERVER timestamps only (§18.2: client clock never feeds
 * analytics; TIME-01). Returns null when either timestamp is missing/invalid.
 */
export function hoursSincePayment(
  serverTimeIso: string | null | undefined,
  firstPaymentAtIso: string | null | undefined
): number | null {
  if (!serverTimeIso || !firstPaymentAtIso) return null;
  const serverMs = Date.parse(serverTimeIso);
  const paymentMs = Date.parse(firstPaymentAtIso);
  if (!Number.isFinite(serverMs) || !Number.isFinite(paymentMs)) return null;
  return Math.max(0, Math.round(((serverMs - paymentMs) / 3_600_000) * 10) / 10);
}
