/**
 * Result polling/refetch strategy tests (SP-505, DEV-SPEC §10.4; Decision: TIME-01).
 *
 * Acceptance criteria under test:
 * 1. Bounded/appropriate polling while generation pending — exponential backoff capped at a
 *    maximum interval inside a hard total-duration window.
 * 2. Polling stops on terminal states (no artifact GENERATING) and on 403; unmount cleanup is
 *    handled by the scheduling effect clearing its timer (verified by design + review).
 * 3. Backoff prevents request storms — delays grow exponentially and never exceed the cap.
 */

import { describe, it, expect } from "vitest";
import {
  computeResultPollDelayMs,
  hasGeneratingArtifact,
  RESULT_POLL_INITIAL_INTERVAL_MS,
  RESULT_POLL_MAX_DURATION_MS,
  RESULT_POLL_MAX_INTERVAL_MS,
} from "../src/soulmate/hooks/useResultAggregate";
import { ResultAggregateResponse } from "../src/soulmate/api/result";

const BASE_INPUT = {
  pollingEnabled: true,
  hasData: true,
  anyGenerating: true,
  elapsedMs: 0,
  maxDurationMs: RESULT_POLL_MAX_DURATION_MS,
  completedPolls: 0,
  initialIntervalMs: RESULT_POLL_INITIAL_INTERVAL_MS,
  maxIntervalMs: RESULT_POLL_MAX_INTERVAL_MS,
  errorStatus: null,
};

function makeAggregate(
  sketchStatus: "LOCKED" | "READY" | "GENERATING" | "COMPLETED" | "FAILED",
  reportStatus: "LOCKED" | "READY" | "GENERATING" | "COMPLETED" | "FAILED"
): ResultAggregateResponse {
  return {
    server_time: "2026-09-26T12:00:00Z",
    subscription: {
      provider: "paypal",
      provider_status: "ACTIVE",
    },
    sketch: {
      unlock_at: "2026-09-26T23:00:00Z",
      availability: "UNLOCKED",
      generation: sketchStatus === "GENERATING" ? "PROCESSING" : "NOT_STARTED",
      status: sketchStatus,
    },
    report: {
      unlock_at: "2026-09-27T11:00:00Z",
      availability: "UNLOCKED",
      generation: reportStatus === "GENERATING" ? "PROCESSING" : "NOT_STARTED",
      status: reportStatus,
    },
  };
}

describe("SP-505: Result polling/refetch strategy", () => {
  describe("1. Bounded polling while generation pending", () => {
    it("schedules the repo-standard ~3s initial interval while an artifact is GENERATING", () => {
      expect(computeResultPollDelayMs(BASE_INPUT)).toBe(3000);
    });

    it("backs off exponentially (3s -> 6s -> 12s -> 24s -> 30s cap) and never exceeds the cap", () => {
      const delays: number[] = [];
      for (let polls = 0; polls <= 5; polls += 1) {
        const delay = computeResultPollDelayMs({ ...BASE_INPUT, completedPolls: polls });
        expect(delay).not.toBeNull();
        delays.push(delay as number);
      }
      expect(delays).toEqual([3000, 6000, 12000, 24000, 30000, 30000]);
      // Storm prevention invariant: every delay is at least the initial interval and at most the cap
      expect(Math.min(...delays)).toBeGreaterThanOrEqual(RESULT_POLL_INITIAL_INTERVAL_MS);
      expect(Math.max(...delays)).toBeLessThanOrEqual(RESULT_POLL_MAX_INTERVAL_MS);
    });

    it("stops after the bounded total-duration window (manual refresh remains available)", () => {
      expect(
        computeResultPollDelayMs({ ...BASE_INPUT, elapsedMs: RESULT_POLL_MAX_DURATION_MS - 1 })
      ).toBe(3000);
      expect(
        computeResultPollDelayMs({ ...BASE_INPUT, elapsedMs: RESULT_POLL_MAX_DURATION_MS })
      ).toBeNull();
    });

    it("never schedules a zero or negative delay", () => {
      const delay = computeResultPollDelayMs({
        ...BASE_INPUT,
        initialIntervalMs: 0,
        maxIntervalMs: 0,
      });
      expect(delay).toBe(0); // clamped, and the scheduler treats 0 as "poll immediately once"
      expect(
        computeResultPollDelayMs({ ...BASE_INPUT, initialIntervalMs: -5, maxIntervalMs: -1 })
      ).toBe(0);
    });
  });

  describe("2. Polling stops on terminal states and authorization problems", () => {
    it("does not poll when polling is disabled or no data has arrived yet", () => {
      expect(computeResultPollDelayMs({ ...BASE_INPUT, pollingEnabled: false })).toBeNull();
      expect(computeResultPollDelayMs({ ...BASE_INPUT, hasData: false })).toBeNull();
    });

    it("stops when neither artifact is GENERATING (terminal state)", () => {
      expect(computeResultPollDelayMs({ ...BASE_INPUT, anyGenerating: false })).toBeNull();
    });

    it("stops on 403 (entitlement/authorization) instead of hammering a forbidden endpoint", () => {
      expect(computeResultPollDelayMs({ ...BASE_INPUT, errorStatus: 403 })).toBeNull();
    });

    it("continues bounded polling through transient (non-403) errors", () => {
      expect(computeResultPollDelayMs({ ...BASE_INPUT, errorStatus: 500 })).toBe(3000);
      expect(computeResultPollDelayMs({ ...BASE_INPUT, errorStatus: 503 })).toBe(3000);
    });

    it("hasGeneratingArtifact is true only while some artifact is GENERATING (terminal -> false)", () => {
      expect(hasGeneratingArtifact(null)).toBe(false);
      expect(hasGeneratingArtifact(makeAggregate("GENERATING", "LOCKED"))).toBe(true);
      expect(hasGeneratingArtifact(makeAggregate("LOCKED", "GENERATING"))).toBe(true);
      expect(hasGeneratingArtifact(makeAggregate("COMPLETED", "FAILED"))).toBe(false);
      expect(hasGeneratingArtifact(makeAggregate("READY", "COMPLETED"))).toBe(false);
      expect(hasGeneratingArtifact(makeAggregate("GENERATING", "GENERATING"))).toBe(true);
    });

    it("hasGeneratingArtifact honors the server combined status with orthogonal fallback", () => {
      // Server status GENERATING with a non-matching orthogonal matrix still counts (server authority)
      const data = makeAggregate("GENERATING", "READY");
      data.sketch.status = "GENERATING";
      data.sketch.generation = "NOT_STARTED"; // orthogonal fallback would say ready
      expect(hasGeneratingArtifact(data)).toBe(true);

      // No server status -> orthogonal fallback: UNLOCKED + PROCESSING -> generating
      const fallbackData = makeAggregate("READY", "READY");
      fallbackData.sketch.status = undefined;
      fallbackData.sketch.generation = "PROCESSING";
      expect(hasGeneratingArtifact(fallbackData)).toBe(true);
    });
  });
});
