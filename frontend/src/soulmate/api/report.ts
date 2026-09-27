/**
 * Report status/content API client (DEV-SPEC §15.11, §10.3, §13; Decisions: TIME-01, RECOVERY-01; SP-702).
 * GET /artifacts/report — authoritative session-scoped state plus, when the combined
 * §10.3 state is COMPLETED, the persisted validated SoulmateReportV1 content
 * (re-validated server-side on every read; the renderer additionally gates it
 * through parseSoulmateReportV1, SP-703).
 * There is no client-triggered generation: the server decides when a report may be
 * generated (REPORT-01/02 keep production generation disabled; SP-706 owns the trigger).
 */

import { clientConfig, ClientConfig } from "../config";
import { parseApiError } from "./errors";
import type { ResultArtifactStatus } from "./result";
import type { SoulmateReportV1 } from "../domain/report";

export interface ReportStatusResponse {
  server_time: string;
  report: ResultArtifactStatus;
  /** Validated SoulmateReportV1 content (camelCase); present only when COMPLETED (SP-702). */
  content?: SoulmateReportV1 | null;
}

export async function getReportStatus(
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<ReportStatusResponse> {
  const queryParam = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await fetch(`${config.apiBaseUrl}/artifacts/report${queryParam}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "include", // Forward session cookie if present
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }
  return res.json();
}
