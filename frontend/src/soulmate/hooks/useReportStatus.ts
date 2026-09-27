"use client";

/**
 * Report status/content data hook (DEV-SPEC §10.3, §15.11; Decisions: TIME-01, RECOVERY-01; SP-702/M5-H01).
 *
 * - Fetches GET /api/soulmate/artifacts/report (authoritative session-scoped state +
 *   validated content when COMPLETED).
 * - Single fetch with manual refresh: no polling and no client-triggered generation
 *   exist for reports yet — the server decides when a report may be generated
 *   (REPORT-01/02 keep production generation disabled; SP-706 owns the trigger and
 *   can add bounded polling alongside it, mirroring useSketchStatus).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getReportStatus, ReportStatusResponse } from "@/soulmate/api/report";

export interface UseReportStatusOptions {
  /** Optional public session ID (must match the authenticated session; IDOR-guarded server-side). */
  sessionId?: string;
  /** When false, no fetch is performed (e.g. fixture preview mode). Defaults to true. */
  enabled?: boolean;
}

export interface UseReportStatusResult {
  data: ReportStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  errorStatus: number | null;
  refresh: () => Promise<void>;
}

export function useReportStatus(options: UseReportStatusOptions = {}): UseReportStatusResult {
  const { sessionId, enabled = true } = options;

  const [data, setData] = useState<ReportStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  const mountedRef = useRef(true);
  const inFlightRef = useRef(false);

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
      if (mountedRef.current) {
        setIsLoading(false);
      }
    }
  }, [sessionId]);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [enabled, refresh]);

  return { data, isLoading, error, errorStatus, refresh };
}

/**
 * Pure §10.3 mapping: server-derived combined status -> Report page view state.
 * LOCKED routes to Result; READY shows the preparing card; GENERATING shows the
 * loading card; COMPLETED renders the persisted validated content; FAILED shows
 * the support state (no client retry exists — generation is server-decided).
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
