"use client";

/**
 * Report status/content data hook (DEV-SPEC §10.3, §15.11; Decisions: TIME-01, REPORT-01; SP-702/SP-706).
 *
 * - Fetches GET /api/soulmate/artifacts/report (authoritative session-scoped state +
 *   validated content when COMPLETED).
 * - Bounded polling (SP-505 pattern, repo-standard scheduler): while the report is
 *   GENERATING, polls with exponential backoff inside a hard duration window; stops
 *   on terminal states, on 403, and on unmount.
 * - `triggerGeneration` calls the idempotent POST endpoint (§13.4 on_demand); the
 *   server — never the client — decides whether a generation may start, so refresh
 *   and repeated clicks can never duplicate a generation or regenerate a completed
 *   report.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getReportStatus,
  triggerReportGeneration,
  ReportStatusResponse,
} from "@/soulmate/api/report";
import { computeResultPollDelayMs } from "./useResultAggregate";

export const REPORT_POLL_INITIAL_INTERVAL_MS = 3000;
export const REPORT_POLL_MAX_INTERVAL_MS = 30000;
export const REPORT_POLL_MAX_DURATION_MS = 10 * 60 * 1000;

export interface UseReportStatusOptions {
  /** Optional public session ID (must match the authenticated session; IDOR-guarded server-side). */
  sessionId?: string;
  /** When false, no fetch is performed (e.g. fixture preview mode). Defaults to true. */
  enabled?: boolean;
  /** Enable bounded background polling while the report is GENERATING (SP-505). */
  polling?: boolean;
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  maxDurationMs?: number;
}

export interface UseReportStatusResult {
  data: ReportStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  errorStatus: number | null;
  isPolling: boolean;
  isTriggering: boolean;
  refresh: () => Promise<void>;
  /** Idempotent enqueue + immediate refetch of the authoritative state. */
  triggerGeneration: () => Promise<void>;
}

function isGenerating(data: ReportStatusResponse | null): boolean {
  return data?.report?.status === "GENERATING";
}

export function useReportStatus(options: UseReportStatusOptions = {}): UseReportStatusResult {
  const {
    sessionId,
    enabled = true,
    polling = false,
    initialIntervalMs = REPORT_POLL_INITIAL_INTERVAL_MS,
    maxIntervalMs = REPORT_POLL_MAX_INTERVAL_MS,
    maxDurationMs = REPORT_POLL_MAX_DURATION_MS,
  } = options;

  const [data, setData] = useState<ReportStatusResponse | null>(null);
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
      const resp = await getReportStatus(sessionId);
      if (!mountedRef.current) return;
      setData(resp);
      setError(null);
      setErrorStatus(null);
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load your report.");
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
      await triggerReportGeneration(sessionId);
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
 * Pure §10.3 mapping: server-derived combined status -> Report page view state.
 * LOCKED routes to Result; READY shows the create CTA; GENERATING shows the
 * loading card; COMPLETED renders the persisted validated content; FAILED shows
 * the support/retry state (server decides retry eligibility, §10.3).
 */
export function deriveReportViewState(
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
