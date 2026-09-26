/**
 * Result Aggregate API Client (DEV-SPEC §10.4, §15.8, Decisions: TIME-01, PAY-AUTH-01, SP-503, SP-504).
 * Single authority call supplying server time, subscription state, and sketch/report statuses.
 * All access decisions derive from persisted server timestamps; client time is display-only.
 */

import { clientConfig, ClientConfig } from "../config";
import { parseApiError } from "./errors";

export type ResultArtifactAvailability = "LOCKED" | "UNLOCKED";

export type ResultArtifactGeneration =
  | "NOT_STARTED"
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export type ResultCombinedStatus =
  | "LOCKED"
  | "READY"
  | "GENERATING"
  | "COMPLETED"
  | "FAILED";

export interface ResultSubscriptionView {
  provider: string;
  provider_status: string;
  first_payment_at?: string | null;
  next_billing_at?: string | null;
}

export interface ResultArtifactStatus {
  unlock_at?: string | null;
  availability: ResultArtifactAvailability;
  generation: ResultArtifactGeneration;
  /** Combined §10.3 state derived server-side (SP-502); preferred by the UI when present. */
  status?: ResultCombinedStatus;
}

export interface ResultAggregateResponse {
  server_time: string;
  subscription?: ResultSubscriptionView | null;
  sketch: ResultArtifactStatus;
  report: ResultArtifactStatus;
}

/**
 * Fetch the Result page aggregate for the authenticated session (DEV-SPEC §10.4, SP-503).
 * Requires a session with a confirmed first payment (PAY-AUTH-01); the backend answers
 * 403 for anonymous, cross-session (IDOR), or unentitled callers.
 */
export async function getResultAggregate(
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<ResultAggregateResponse> {
  const queryParam = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const url = `${config.apiBaseUrl}/result${queryParam}`;

  const res = await fetch(url, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
    credentials: "include", // Forward session cookie if present
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}
