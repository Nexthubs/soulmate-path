/**
 * Domain types and state derivation for Result & Countdown State Machine (DEV-SPEC §10).
 */

export type ArtifactAvailability = "LOCKED" | "UNLOCKED";

export type ArtifactGeneration =
  | "NOT_STARTED"
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export type CombinedUIState =
  | "countdown"
  | "ready"
  | "generating"
  | "completed"
  | "failed";

export type ArtifactType = "sketch" | "report";

export interface ArtifactItemState {
  /** Persisted unlock timestamp (ISO). Null/undefined = placeholder row missing; server self-heal restores it. */
  unlock_at?: string | null;
  availability: ArtifactAvailability;
  generation: ArtifactGeneration;
  /** Combined §10.3 state derived server-side (SP-502). Preferred over local derivation when present. */
  status?: "LOCKED" | "READY" | "GENERATING" | "COMPLETED" | "FAILED";
  artifact_url?: string;
  error_message?: string;
}

export interface ResultAggregateData {
  server_time: string;
  subscription?: {
    provider: string;
    provider_status: string;
    first_payment_at?: string | null;
    next_billing_at?: string | null;
  } | null;
  sketch: ArtifactItemState;
  report: ArtifactItemState;
}

/**
 * TIME-01 Boundary Note: Server-side calculation in SP-502/SP-503 is authoritative.
 * UI presentation reflects server state; reaching zero countdown never authorizes unlock.
 *
 * Derives the Combined UI State from orthogonal availability and generation states (DEV-SPEC §10.3).
 *
 * Rules:
 * | Availability | Generation         | UI State    |
 * |--------------|--------------------|-------------|
 * | LOCKED       | any                | countdown   |
 * | UNLOCKED     | NOT_STARTED        | ready       |
 * | UNLOCKED     | QUEUED/PROCESSING  | generating  |
 * | UNLOCKED     | COMPLETED          | completed   |
 * | UNLOCKED     | FAILED             | failed      |
 */
export function deriveCombinedUIState(item: ArtifactItemState): CombinedUIState {
  // Server-derived combined status (SP-502/SP-503) is the authority when present.
  if (item.status) {
    switch (item.status) {
      case "LOCKED":
        return "countdown";
      case "READY":
        return "ready";
      case "GENERATING":
        return "generating";
      case "COMPLETED":
        return "completed";
      case "FAILED":
        return "failed";
    }
  }

  if (item.availability === "LOCKED") {
    return "countdown";
  }

  switch (item.generation) {
    case "NOT_STARTED":
      return "ready";
    case "QUEUED":
    case "PROCESSING":
      return "generating";
    case "COMPLETED":
      return "completed";
    case "FAILED":
      return "failed";
    default:
      return "countdown";
  }
}

/**
 * Formats a total duration in seconds into hh:mm:ss string.
 */
export function formatCountdown(totalSeconds: number): string {
  if (totalSeconds <= 0) return "00:00:00";
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);

  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

/**
 * Computes remaining seconds until target unlock time calibrated against authoritative server time (TIME-01).
 */
export function calculateRemainingSeconds(
  unlockAtIso: string | null | undefined,
  serverTimeIso: string
): number {
  if (!unlockAtIso) return 0;
  const target = new Date(unlockAtIso).getTime();
  const server = new Date(serverTimeIso).getTime();
  if (isNaN(target) || isNaN(server)) return 0;
  const diffMs = target - server;
  return Math.max(0, Math.floor(diffMs / 1000));
}

/**
 * Computes the client-to-server clock offset in milliseconds (SP-504, TIME-01).
 * Positive = server clock is ahead of the client clock. A null/invalid server
 * time yields 0 (client clock assumed — display-only fallback for fixtures).
 */
export function calculateServerClockOffsetMs(
  serverTimeIso: string | null | undefined,
  clientNowMs: number = Date.now()
): number {
  if (!serverTimeIso) return 0;
  const server = new Date(serverTimeIso).getTime();
  if (isNaN(server)) return 0;
  return server - clientNowMs;
}

/**
 * Remaining seconds until unlock, calibrated by the server clock offset (SP-504, TIME-01).
 * The countdown is anchored to server time via the offset captured at the last fetch, so a
 * wrong or manipulated client clock cannot change the displayed or derived unlock behavior.
 * Recomputed from absolute timestamps each call: immune to tab-sleep drift.
 */
export function getCalibratedRemainingSeconds(
  unlockAtIso: string | null | undefined,
  clockOffsetMs: number,
  clientNowMs: number = Date.now()
): number {
  if (!unlockAtIso) return 0;
  const target = new Date(unlockAtIso).getTime();
  if (isNaN(target)) return 0;
  const serverNowMs = clientNowMs + clockOffsetMs;
  const diffMs = target - serverNowMs;
  return Math.max(0, Math.floor(diffMs / 1000));
}

/**
 * Pure decision for the zero-countdown refetch signal (SP-504, TIME-01).
 *
 * When the calibrated countdown reaches zero while the server still reports LOCKED, the card
 * must notify the parent once per `unlock_at` so the parent refetches server state; the server
 * response — never the local zero — decides whether content unlocks. A positive remaining time
 * resets the one-shot guard (e.g. after a refetch returns a later unlock time).
 */
export function evaluateCountdownZeroNotification(
  uiState: CombinedUIState,
  remainingSeconds: number,
  unlockAt: string | null | undefined,
  lastNotifiedUnlock: string | null
): { notify: boolean; nextLastNotifiedUnlock: string | null } {
  if (uiState === "countdown" && remainingSeconds <= 0 && unlockAt) {
    if (lastNotifiedUnlock !== unlockAt) {
      return { notify: true, nextLastNotifiedUnlock: unlockAt };
    }
    return { notify: false, nextLastNotifiedUnlock: lastNotifiedUnlock };
  }
  if (remainingSeconds > 0) {
    return { notify: false, nextLastNotifiedUnlock: null };
  }
  return { notify: false, nextLastNotifiedUnlock: lastNotifiedUnlock };
}
