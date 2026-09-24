/**
 * Soulmate Route Guard API Client (DEV-SPEC §3, §10, §20, SP-304, Decisions: PAY-AUTH-01, TIME-01).
 * Queries server-authoritative route access verdict and redirection guidance.
 */

import { clientConfig, ClientConfig } from "../config";
import { parseApiError } from "./errors";

export interface RouteGuardResponse {
  allowed: boolean;
  target_route: string;
  redirect_to?: string | null;
  reason?: string | null;
  server_time: string;
  session_id?: string | null;
  quiz_completed: boolean;
  email_captured: boolean;
  is_paid: boolean;
  sketch_unlocked: boolean;
  report_unlocked: boolean;
  sketch_unlock_at?: string | null;
  report_unlock_at?: string | null;
}

/**
 * Check whether the session is authorized to view targetRoute per DEV-SPEC §3 table.
 * Server state is the final authority.
 */
export async function checkRouteGuard(
  targetRoute: string,
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<RouteGuardResponse> {
  const params = new URLSearchParams({ target_route: targetRoute });
  if (sessionId) {
    params.set("session_id", sessionId);
  }

  const url = `${config.apiBaseUrl}/guard/check?${params.toString()}`;

  const res = await fetch(url, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
    credentials: "include", // Forward HttpOnly session cookie
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}
