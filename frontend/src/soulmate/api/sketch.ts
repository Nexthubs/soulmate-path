/**
 * Sketch status/asset API client (DEV-SPEC §15.10, §10.3, §11; Decisions: ASSET-01, TIME-01; SP-607).
 * GET /artifacts/sketch — authoritative session-scoped state + persisted display URL.
 * POST /artifacts/sketch/generate — idempotent enqueue (§11.5/§11.6); the server,
 * never the client, decides whether a generation may start.
 */

import { clientConfig, ClientConfig } from "../config";
import { parseApiError } from "./errors";
import type { ResultArtifactStatus } from "./result";

export interface SketchStatusResponse {
  server_time: string;
  sketch: ResultArtifactStatus;
  /** Display URL of the persisted durable asset; present only when COMPLETED (ASSET-01). */
  image_url?: string | null;
  /** Project-owned object storage key (§11.7); present only when COMPLETED. */
  storage_key?: string | null;
}

/** POST /artifacts/sketch/generate additionally reports the durable job state (§11.6). */
export interface SketchTriggerResponse extends SketchStatusResponse {
  job_status?: string | null;
}

async function sketchRequest(
  path: string,
  method: "GET" | "POST",
  sessionId: string | undefined,
  config: ClientConfig
): Promise<SketchStatusResponse> {
  const queryParam = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await fetch(`${config.apiBaseUrl}${path}${queryParam}`, {
    method,
    headers: { Accept: "application/json" },
    credentials: "include", // Forward session cookie if present
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }
  return res.json();
}

/**
 * Fetch the sketch status (and asset URL when COMPLETED) for the authenticated
 * session. Requires a confirmed first payment (PAY-AUTH-01); the backend answers
 * 403 for anonymous, cross-session (IDOR), or unentitled callers.
 */
export async function getSketchStatus(
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<SketchStatusResponse> {
  return sketchRequest("/artifacts/sketch", "GET", sessionId, config);
}

/**
 * Trigger the (idempotent) sketch generation. Safe to call repeatedly: COMPLETED
 * artifacts never regenerate and concurrent triggers converge on one durable job
 * (§11.5/§11.6). The response carries the post-enqueue status.
 */
export async function triggerSketchGeneration(
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<SketchTriggerResponse> {
  return sketchRequest("/artifacts/sketch/generate", "POST", sessionId, config);
}
