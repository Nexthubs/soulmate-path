"use client";

/**
 * Result aggregate data hook (DEV-SPEC §10.4, Decisions: TIME-01, PAY-AUTH-01, SP-503–SP-505).
 *
 * - Fetches GET /api/soulmate/result and recalibrates the client-to-server clock offset from
 *   `server_time` on EVERY successful fetch (TIME-01: persisted server time is authoritative).
 * - Exposes `onCountdownZero` for the cards: a locally-reached zero countdown triggers a server
 *   refetch; the server response — never the local zero — decides the unlock.
 * - Optional bounded polling (SP-505): while an artifact is GENERATING, polls with exponential
 *   backoff (repo-standard ~3s initial, capped) inside a hard total-duration window; stops on
 *   terminal states, on 403, and on unmount. Payment-pending polling remains owned by the
 *   payment-processing page (DEV-SPEC §15.8, SP-410).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getResultAggregate,
  ResultAggregateResponse,
} from "@/soulmate/api/result";
import {
  calculateServerClockOffsetMs,
  deriveCombinedUIState,
} from "@/soulmate/components/result/types";

/** Repo-standard initial cadence (DEV-SPEC §15.8 suggests 2–3s polling). */
export const RESULT_POLL_INITIAL_INTERVAL_MS = 3000;
/** Backoff cap so a long generation cannot become a request storm (SP-505). */
export const RESULT_POLL_MAX_INTERVAL_MS = 30000;
/** Hard bound on a single polling session; manual refresh remains available afterwards. */
export const RESULT_POLL_MAX_DURATION_MS = 10 * 60 * 1000;

export interface UseResultAggregateOptions {
  /** Optional public session ID (must match the authenticated session; IDOR-guarded server-side). */
  sessionId?: string;
  /** When false, no fetch is performed (e.g. fixture preview mode). Defaults to true. */
  enabled?: boolean;
  /** Enable bounded background polling while an artifact is GENERATING (SP-505). */
  polling?: boolean;
  /** Polling tuning (exported constants by default). */
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  maxDurationMs?: number;
}

export interface ResultPollDecisionInput {
  pollingEnabled: boolean;
  hasData: boolean;
  anyGenerating: boolean;
  elapsedMs: number;
  maxDurationMs: number;
  completedPolls: number;
  initialIntervalMs: number;
  maxIntervalMs: number;
  errorStatus: number | null;
}

/**
 * Pure polling scheduler decision (SP-505). Returns the delay in ms before the next poll,
 * or null to stop polling. Bounded by design:
 * - exponential backoff: initialInterval * 2^completedPolls, capped at maxInterval;
 * - hard total-duration window (elapsedMs >= maxDurationMs -> stop; manual refresh remains);
 * - stops on terminal states (no artifact GENERATING) and on 403 (authorization/entitlement);
 * - unmount cleanup is handled by the effect clearing its timer.
 */
export function computeResultPollDelayMs(input: ResultPollDecisionInput): number | null {
  const {
    pollingEnabled,
    hasData,
    anyGenerating,
    elapsedMs,
    maxDurationMs,
    completedPolls,
    initialIntervalMs,
    maxIntervalMs,
    errorStatus,
  } = input;

  if (!pollingEnabled) return null;
  if (!hasData) return null;
  if (!anyGenerating) return null;
  if (errorStatus === 403) return null;
  if (elapsedMs >= maxDurationMs) return null;

  const backoff = Math.min(
    initialIntervalMs * Math.pow(2, Math.max(0, completedPolls)),
    maxIntervalMs
  );
  return Math.max(0, backoff);
}

/**
 * True while any artifact is in a non-terminal GENERATING state (server `status` preferred,
 * orthogonal availability×generation fallback), i.e. the only state worth polling on Result.
 */
export function hasGeneratingArtifact(data: ResultAggregateResponse | null): boolean {
  if (!data) return false;
  return (
    deriveCombinedUIState(data.sketch) === "generating" ||
    deriveCombinedUIState(data.report) === "generating"
  );
}

export interface UseResultAggregateResult {
  data: ResultAggregateResponse | null;
  /** Client-to-server clock offset in milliseconds, recalibrated at every successful fetch. */
  clockOffsetMs: number;
  isLoading: boolean;
  error: string | null;
  /** HTTP status of the failed fetch (e.g. 403 for anonymous/IDOR/unentitled), if any. */
  errorStatus: number | null;
  /** True while bounded polling is actively scheduled (SP-505). */
  isPolling: boolean;
  /** Manually refetch the aggregate (recalibrates the clock offset from the fresh server_time). */
  refresh: () => Promise<void>;
  /** Card callback: countdown reached zero locally while LOCKED -> refetch server state. */
  onCountdownZero: () => void;
}

export function useResultAggregate(
  options: UseResultAggregateOptions = {}
): UseResultAggregateResult {
  const {
    sessionId,
    enabled = true,
    polling = false,
    initialIntervalMs = RESULT_POLL_INITIAL_INTERVAL_MS,
    maxIntervalMs = RESULT_POLL_MAX_INTERVAL_MS,
    maxDurationMs = RESULT_POLL_MAX_DURATION_MS,
  } = options;

  const [data, setData] = useState<ResultAggregateResponse | null>(null);
  const [clockOffsetMs, setClockOffsetMs] = useState(0);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  const mountedRef = useRef(true);
  const inFlightRef = useRef(false);
  /** Increments after every fetch attempt (success or failure) to drive the poll scheduler. */
  const [fetchVersion, setFetchVersion] = useState(0);
  const pollCompletedRef = useRef(0);
  const pollStartRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchAggregate = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const resp = await getResultAggregate(sessionId);
      if (!mountedRef.current) return;
      // TIME-01 recalibration: anchor the countdown to the fresh authoritative server time.
      setClockOffsetMs(calculateServerClockOffsetMs(resp.server_time));
      setData(resp);
      setError(null);
      setErrorStatus(null);
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load your results.");
      setErrorStatus(
        typeof err === "object" && err !== null && "status" in err
          ? Number((err as { status: unknown }).status)
          : null
      );
    } finally {
      inFlightRef.current = false;
      pollCompletedRef.current += 1;
      if (mountedRef.current) {
        setIsLoading(false);
        setFetchVersion((v) => v + 1);
      }
    }
  }, [sessionId]);

  useEffect(() => {
    if (!enabled) return;
    void fetchAggregate();
  }, [enabled, fetchAggregate]);

  // ------------------------------------------------------------------
  // Bounded polling scheduler (SP-505): exponential backoff, terminal/403/duration stop.
  // The effect re-runs after every fetch attempt (fetchVersion) and re-decides.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!polling || !enabled) {
      pollStartRef.current = null;
      pollCompletedRef.current = 0;
      setIsPolling(false);
      return;
    }

    const anyGenerating = hasGeneratingArtifact(data);
    if (!anyGenerating) {
      // Terminal state (or nothing to wait for): stop and reset the bounded window so a
      // future generation session (e.g. after Retry) starts a fresh backoff curve.
      pollStartRef.current = null;
      pollCompletedRef.current = 0;
      setIsPolling(false);
      return;
    }

    if (pollStartRef.current === null) {
      pollStartRef.current = Date.now();
      pollCompletedRef.current = 0;
    }
    const elapsedMs = Date.now() - pollStartRef.current;

    const delay = computeResultPollDelayMs({
      pollingEnabled: true,
      hasData: data !== null,
      anyGenerating,
      elapsedMs,
      maxDurationMs,
      completedPolls: pollCompletedRef.current,
      initialIntervalMs,
      maxIntervalMs,
      errorStatus,
    });

    if (delay === null) {
      pollStartRef.current = null;
      pollCompletedRef.current = 0;
      setIsPolling(false);
      return;
    }

    setIsPolling(true);
    const timer = setTimeout(() => {
      void fetchAggregate();
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [polling, enabled, data, errorStatus, fetchVersion, fetchAggregate, initialIntervalMs, maxIntervalMs, maxDurationMs]);

  const onCountdownZero = useCallback(() => {
    // A locally-reached zero never unlocks content; refetch and let the server decide (TIME-01).
    void fetchAggregate();
  }, [fetchAggregate]);

  return {
    data,
    clockOffsetMs,
    isLoading,
    error,
    errorStatus,
    isPolling,
    refresh: fetchAggregate,
    onCountdownZero,
  };
}
