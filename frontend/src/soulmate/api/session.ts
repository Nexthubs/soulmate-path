/**
 * Soulmate Session API Client (DEV-SPEC §6, §15.1, SP-201).
 * Supports session initialization, cookie persistence, and UI state recovery.
 */

import { clientConfig, ClientConfig } from "../config";
import { SoulmateProfileV1 } from "../domain/profile";
import { QuizConfig } from "../quiz/types";
import { parseApiError } from "./errors";

export type { SoulmateProfileV1, QuizConfig };

export interface SessionCreateResponse {
  session_id: string;
  quiz_version: string;
  current_step: string;
  status: string;
}

export interface SavedAnswerDetail {
  question_code: string;
  answer: Record<string, unknown>;
  value?: unknown;
  values?: unknown[];
  duration_ms?: number | null;
  answered_at?: string | null;
}

export interface SessionCurrentResponse {
  session_id: string;
  quiz_version: string;
  status: string;
  current_step: string;
  email?: string | null;
  quiz_completed_at?: string | null;
  answers: Record<string, SavedAnswerDetail>;
  saved_answers_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * Initializes a new anonymous Soulmate session.
 * The server sets a secure HttpOnly cookie ('soulmate_sid') automatically.
 */
export async function createSession(
  utmJson: Record<string, unknown> = {},
  config: ClientConfig = clientConfig
): Promise<SessionCreateResponse> {
  const url = `${config.apiBaseUrl}/sessions`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ utm_json: utmJson }),
    credentials: "include", // Forward and persist HttpOnly cookies
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as SessionCreateResponse;
}

/**
 * Recovers caller's active session using HttpOnly credentials.
 * Returns step, status, and saved answers for UI restoration.
 */
export async function getCurrentSession(
  config: ClientConfig = clientConfig
): Promise<SessionCurrentResponse> {
  const url = `${config.apiBaseUrl}/sessions/current`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include", // Send HttpOnly cookie
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as SessionCurrentResponse;
}

/**
 * Retrieves session by public ID with IDOR guard.
 */
export async function getSession(
  sessionId: string,
  config: ClientConfig = clientConfig
): Promise<SessionCurrentResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as SessionCurrentResponse;
}

export interface AnswerSubmitPayload {
  value?: string;
  values?: string[];
  duration_ms?: number;
}

export interface AnswerSubmitResponse {
  saved: boolean;
  question_code: string;
  next_step: string;
  zodiac?: {
    sign: string;
    label: string;
  } | null;
}


/**
 * Submits or updates an answer to a question (DEV-SPEC §15.3, SP-202).
 * Atomically upserts answer and advances current step.
 */
export async function submitAnswer(
  sessionId: string,
  questionCode: string,
  payload: AnswerSubmitPayload,
  config: ClientConfig = clientConfig
): Promise<AnswerSubmitResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/answers/${encodeURIComponent(questionCode)}`;

  const res = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as AnswerSubmitResponse;
}
export interface FlowStateResponse {
  session_id: string;
  current_step: string;
  step_type: string;
  next_step: string | null;
  previous_step: string | null;
  progress_percent: number;
  is_quiz_completed: boolean;
  step_metadata?: Record<string, unknown> | null;
}

export interface TransitionContinueResponse {
  transition_code: string;
  next_step: string;
  flow_state: FlowStateResponse;
}

/**
 * Resolves authoritative flow state including step type, next/previous step,
 * progress percentage, and dynamic copy metadata (DEV-SPEC §1.1, §4, §15.3, SP-203).
 */
export async function getFlowState(
  sessionId: string,
  config: ClientConfig = clientConfig
): Promise<FlowStateResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/flow/state`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as FlowStateResponse;
}

/**
 * Advances a transition screen after prerequisite verification.
 */
export async function continueTransition(
  sessionId: string,
  transitionCode: string,
  config: ClientConfig = clientConfig
): Promise<TransitionContinueResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/transitions/${encodeURIComponent(transitionCode)}/continue`;

  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as TransitionContinueResponse;
}

/**
 * Navigates to the canonical previous step while preserving all saved answers.
 */
export async function navigateBack(
  sessionId: string,
  config: ClientConfig = clientConfig
): Promise<FlowStateResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/step/back`;

  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as FlowStateResponse;
}

/**
 * Fetches the canonical normalized Soulmate Profile for an authenticated session (DEV-SPEC §7).
 */
export async function getSessionProfile(
  sessionId: string,
  config: ClientConfig = clientConfig
): Promise<SoulmateProfileV1> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/profile`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as SoulmateProfileV1;
}

export type InterstitialCode =
  | "spiritual_person"
  | "familiar_psychic_artistry"
  | "warning_response";

export interface InterstitialSubmitResponse {
  saved: boolean;
  interstitial_code: string;
  value: boolean | string;
  next_step: string;
  flow_state?: FlowStateResponse;
}

/**
 * Submits or edits an answer to a post-quiz interstitial modal (DEV-SPEC §5.7, §15.4, SP-206).
 */
export async function submitInterstitialAnswer(
  sessionId: string,
  code: InterstitialCode | string,
  value: boolean | string,
  durationMs?: number,
  config: ClientConfig = clientConfig
): Promise<InterstitialSubmitResponse> {
  const url = `${config.apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/interstitials/${encodeURIComponent(code)}`;

  const body: Record<string, unknown> = { value };
  if (typeof durationMs === "number") {
    body.duration_ms = durationMs;
  }

  const res = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as InterstitialSubmitResponse;
}

/**
 * Fetches immutable Quiz configuration from server (DEV-SPEC §15.2).
 * Optionally specifies version string or retrieves the active session's pinned configuration.
 */
export async function getQuizConfig(
  version?: string,
  config: ClientConfig = clientConfig
): Promise<QuizConfig> {
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  const url = `${config.apiBaseUrl}/quiz/config${query}`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
  });

  if (!res.ok) {
    const errorPayload = await res.json().catch(() => null);
    throw parseApiError(res.status, errorPayload);
  }

  return (await res.json()) as QuizConfig;
}

