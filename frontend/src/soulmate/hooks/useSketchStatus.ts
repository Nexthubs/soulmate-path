"use client";

/**
 * Sketch status data hook (DEV-SPEC §10.3, §15.10; Decisions: TIME-01, ASSET-01; SP-607).
 *
 * - Fetches GET /api/soulmate/artifacts/sketch (authoritative session-scoped state).
 * - Bounded polling (SP-505 pattern, reusing the repo-standard scheduler): while the
 *   sketch is GENERATING, polls with exponential backoff inside a hard duration window;
 *   stops on terminal states, on 403, and on unmount.
 * - `triggerGeneration` calls the idempotent POST endpoint; the server — never the
 *   client — decides whether a generation may start (§11.5/§11.6), so refresh and
 *   repeated clicks can never duplicate a generation.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSketchStatus,
  triggerSketchGeneration,
  SketchStatusResponse,
} from "@/soulmate/api/sketch";
import { computeResultPollDelayMs } from "./useResultAggregate";

export const SKETCH_POLL_INITIAL_INTERVAL_MS = 3000;
export const SKETCH_POLL_MAX_INTERVAL_MS = 30000;
export const SKETCH_POLL_MAX_DURATION_MS = 10 * 60 * 1000;

export interface UseSketchStatusOptions {
  /** Optional public session ID (must match the authenticated session; IDOR-guarded server-side). */
  sessionId?: string;
  /** When false, no fetch is performed (e.g. fixture preview mode). Defaults to true. */
  enabled?: boolean;
  /** Enable bounded background polling while the sketch is GENERATING (SP-505). */
  polling?: boolean;
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  maxDurationMs?: number;
}

export interface UseSketchStatusResult {
  data: SketchStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  errorStatus: number | null;
  isPolling: boolean;
  isTriggering: boolean;
  refresh: () => Promise<void>;
  /** Idempotent enqueue + immediate refetch of the authoritative state. */
  triggerGeneration: () => Promise<void>;
}

function isGenerating(data: SketchStatusResponse | null): boolean {
  return data?.sketch?.status === "GENERATING";
}

export function useSketchStatus(options: UseSketchStatusOptions = {}): UseSketchStatusResult {
  const {
    sessionId,
    enabled = true,
    polling = false,
    initialIntervalMs = SKETCH_POLL_INITIAL_INTERVAL_MS,
    maxIntervalMs = SKETCH_POLL_MAX_INTERVAL_MS,
    maxDurationMs = SKETCH_POLL_MAX_DURATION_MS,
  } = options;

  const [data, setData] = useState<SketchStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);

  const mountedRef = useRef(true);
  const inFlightRef = useRef(false);
  const [fetchVersion, setFetchVersion] = useState(0);
  const pollCompletedRef = useRef(0);
  const pollStartRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const resp = await getSketchStatus(sessionId);
      if (!mountedRef.current) return;
      setData(resp);
      setError(null);
      setErrorStatus(null);
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load your sketch.");
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
    void refresh();
  }, [enabled, refresh]);

  const triggerGeneration = useCallback(async () => {
    if (isTriggering) return;
    setIsTriggering(true);
    try {
      // Idempotent server-side enqueue; then let the authoritative state decide.
      await triggerSketchGeneration(sessionId);
      await refresh();
    } finally {
      if (mountedRef.current) setIsTriggering(false);
    }
  }, [isTriggering, sessionId, refresh]);

  // Bounded polling scheduler (SP-505): re-decides after every fetch attempt.
  useEffect(() => {
    if (!polling || !enabled || isTriggering) {
      if (!polling || !enabled) {
        pollStartRef.current = null;
        pollCompletedRef.current = 0;
        setIsPolling(false);
      }
      return;
    }

    const generating = isGenerating(data);
    if (!generating) {
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
      anyGenerating: generating,
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
      void refresh();
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [polling, enabled, data, errorStatus, fetchVersion, refresh, initialIntervalMs, maxIntervalMs, maxDurationMs, isTriggering]);

  return {
    data,
    isLoading,
    error,
    errorStatus,
    isPolling,
    isTriggering,
    refresh,
    triggerGeneration,
  };
}

/**
 * Pure §10.3 mapping: server-derived combined status -> Sketch page view state.
 * LOCKED routes to Result; UNLOCKED+NOT_STARTED shows the Ready/Check-Now card;
 * COMPLETED displays the persisted asset; FAILED follows the retry/support policy.
 */
export function deriveSketchViewState(
  status: string | null | undefined
): "locked" | "ready" | "loading" | "completed" | "failed" | null {
  switch (status) {
    case "LOCKED":
      return "locked";
    case "READY":
      return "ready";
    case "GENERATING":
      return "loading";
    case "COMPLETED":
      return "completed";
    case "FAILED":
      return "failed";
    default:
      return null; // unknown / not yet loaded
  }
}
