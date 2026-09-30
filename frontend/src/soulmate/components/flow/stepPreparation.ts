import type { FlowStateResponse } from "@/soulmate/api/session";

/**
 * Phase-switch preparation store (batch 3, `docs/UI-IMPROVEMENT-EXECUTION-PLAN.md` §6).
 *
 * Pure, framework-free in-memory cache for per-`sessionId+step` prepared flow
 * metadata with idle/pending/ready/error states:
 * - `ensure` reuses ready AND in-flight preparations for the same session+target
 *   so the departure page and the destination page share one request (§6.2.3);
 * - only errored entries may be retried with a fresh request;
 * - a resolved response never overwrites a newer entry for the same key (§6.2.4);
 * - `invalidateExcept` / `clear` implement the Back / new-step / new-session
 *   invalidation rules.
 *
 * The store only guarantees WHAT was fetched; consumers must still validate
 * `flowState.session_id` and `flowState.current_step` against the step they
 * intended to visit (server authority, DEV-SPEC §3/§6).
 *
 * Entries live for the current page lifetime only — never persisted.
 */
export type PrepareStatus = "pending" | "ready" | "error";

export interface PreparedStepEntry {
  status: PrepareStatus;
  sessionId: string;
  step: string;
  flowState: FlowStateResponse | null;
  error: string | null;
  promise: Promise<PreparedStepEntry> | null;
}

export interface StepPreparationStore {
  ensure(sessionId: string, step: string): Promise<PreparedStepEntry>;
  get(sessionId: string, step: string): PreparedStepEntry | null;
  /** Drop every prepared entry whose step !== keepStep (null prunes all). */
  invalidateExcept(keepStep: string | null): void;
  /** Drop everything (new session). */
  clear(): void;
  size(): number;
}

export function createStepPreparationStore(
  fetchFlowState: (sessionId: string) => Promise<FlowStateResponse>
): StepPreparationStore {
  const entries = new Map<string, PreparedStepEntry>();
  const keyOf = (sessionId: string, step: string) => `${sessionId}:${step}`;

  function ensure(sessionId: string, step: string): Promise<PreparedStepEntry> {
    const key = keyOf(sessionId, step);
    const existing = entries.get(key);
    if (existing && existing.status !== "error" && existing.promise) {
      return existing.promise;
    }

    const entry: PreparedStepEntry = {
      status: "pending",
      sessionId,
      step,
      flowState: null,
      error: null,
      promise: null,
    };
    entries.set(key, entry);
    entry.promise = fetchFlowState(sessionId).then(
      (state) => {
        if (entries.get(key) === entry) {
          entry.status = "ready";
          entry.flowState = state;
        }
        return entry;
      },
      (err: unknown) => {
        if (entries.get(key) === entry) {
          entry.status = "error";
          entry.error = err instanceof Error ? err.message : String(err);
        }
        return entry;
      }
    );
    return entry.promise;
  }

  function get(sessionId: string, step: string): PreparedStepEntry | null {
    return entries.get(keyOf(sessionId, step)) ?? null;
  }

  function invalidateExcept(keepStep: string | null): void {
    for (const [key, entry] of entries) {
      if (keepStep === null || entry.step !== keepStep) {
        entries.delete(key);
      }
    }
  }

  function clear(): void {
    entries.clear();
  }

  function size(): number {
    return entries.size;
  }

  return { ensure, get, invalidateExcept, clear, size };
}
