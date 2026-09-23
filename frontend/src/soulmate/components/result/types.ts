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
  unlock_at: string;
  availability: ArtifactAvailability;
  generation: ArtifactGeneration;
  artifact_url?: string;
  error_message?: string;
}

export interface ResultAggregateData {
  server_time: string;
  subscription?: {
    provider: string;
    provider_status: string;
    first_payment_at: string;
    next_billing_at: string;
  };
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
  unlockAtIso: string,
  serverTimeIso: string
): number {
  const target = new Date(unlockAtIso).getTime();
  const server = new Date(serverTimeIso).getTime();
  if (isNaN(target) || isNaN(server)) return 0;
  const diffMs = target - server;
  return Math.max(0, Math.floor(diffMs / 1000));
}
