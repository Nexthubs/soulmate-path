/**
 * Live Sketch page tests (SP-607, DEV-SPEC §10.3, §15.10; Decisions: ASSET-01, TIME-01).
 *
 * Acceptance criteria under test:
 * - §10.3 mapping: LOCKED→route-to-Result signal, READY→check-now, GENERATING→loading,
 *   COMPLETED→completed, FAILED→failed (server-derived status is the single authority);
 * - ready state CTA wiring (idempotent trigger; disabled while in flight);
 * - sketch API client: correct endpoints/credentials handling and ASSET-01 fields
 *   (image_url/storage_key surfaced only for completed assets);
 * - polling decision reuse from the repo-standard SP-505 scheduler.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SketchViewer } from "../src/soulmate/components/sketch";
import { deriveSketchViewState } from "../src/soulmate/hooks/useSketchStatus";
import { getSketchStatus, triggerSketchGeneration } from "../src/soulmate/api/sketch";
import { computeResultPollDelayMs } from "../src/soulmate/hooks/useResultAggregate";
import { ClientConfig } from "../src/soulmate/config";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
    replace: vi.fn(),
  }),
}));

const mockConfig: ClientConfig = {
  appBaseUrl: "http://localhost:3000",
  apiBaseUrl: "http://localhost:8000/api/soulmate",
  paypalClientId: "mock_client_id",
  currency: "USD",
  introPrice: "19.00",
  regularPrice: "29.00",
};

describe("SP-607: deriveSketchViewState (§10.3 mapping)", () => {
  it("maps every server-derived combined status to the correct view state", () => {
    expect(deriveSketchViewState("LOCKED")).toBe("locked");
    expect(deriveSketchViewState("READY")).toBe("ready");
    expect(deriveSketchViewState("GENERATING")).toBe("loading");
    expect(deriveSketchViewState("COMPLETED")).toBe("completed");
    expect(deriveSketchViewState("FAILED")).toBe("failed");
  });

  it("returns null for unknown/unloaded status so the page keeps its previous state", () => {
    expect(deriveSketchViewState(null)).toBeNull();
    expect(deriveSketchViewState(undefined)).toBeNull();
    expect(deriveSketchViewState("SOMETHING_ELSE")).toBeNull();
  });
});

describe("SP-607: SketchViewer ready state (UNLOCKED + NOT_STARTED)", () => {
  it("renders the ready card with a Generate CTA", () => {
    const html = renderToStaticMarkup(
      <SketchViewer state="ready" onCheckNow={() => {}} />
    );
    expect(html).toContain('data-testid="sketch-ready-state"');
    expect(html).toContain('data-testid="sketch-check-now-cta"');
    expect(html).toContain("Generate My Sketch");
  });

  it("disables the CTA while the trigger request is in flight", () => {
    const html = renderToStaticMarkup(
      <SketchViewer state="ready" onCheckNow={() => {}} isTriggering={true} />
    );
    expect(html).toContain("Starting...");
    expect(html).toMatch(/disabled=""/);
  });
});

describe("SP-607: sketch API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getSketchStatus GETs /artifacts/sketch with credentials and parses the asset fields", async () => {
    const payload = {
      server_time: "2026-09-26T12:00:00Z",
      sketch: { unlock_at: null, availability: "UNLOCKED", generation: "COMPLETED", status: "COMPLETED" },
      image_url: "https://cdn.example.com/assets/soulmate/sketches/abc/original.webp",
      storage_key: "soulmate/sketches/abc/original.webp",
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => payload,
    } as Response);

    const data = await getSketchStatus("sess_123", mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/artifacts/sketch?session_id=sess_123",
      expect.objectContaining({ method: "GET", credentials: "include" })
    );
    expect(data.sketch.status).toBe("COMPLETED");
    expect(data.image_url).toContain("original.webp");
    expect(data.storage_key).toContain("soulmate/sketches");
  });

  it("triggerSketchGeneration POSTs the idempotent generate endpoint", async () => {
    const payload = {
      server_time: "2026-09-26T12:00:00Z",
      sketch: { unlock_at: null, availability: "UNLOCKED", generation: "QUEUED", status: "GENERATING" },
      job_status: "QUEUED",
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => payload,
    } as Response);

    const data = await triggerSketchGeneration(undefined, mockConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/artifacts/sketch/generate",
      expect.objectContaining({ method: "POST", credentials: "include" })
    );
    expect(data.sketch.status).toBe("GENERATING");
    expect(data.job_status).toBe("QUEUED");
  });

  it("surfaces 403 as a parseable domain error (anonymous/unentitled callers)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ error_code: "FORBIDDEN_OWNERSHIP", message: "denied", request_id: "r1" }),
    } as Response);

    await expect(getSketchStatus(undefined, mockConfig)).rejects.toSatisfy((err: unknown) => {
      const parsed = err as { status?: number };
      return parsed.status === 403;
    });
  });
});

describe("SP-607: bounded polling while GENERATING (SP-505 scheduler reuse)", () => {
  const BASE = {
    pollingEnabled: true,
    hasData: true,
    anyGenerating: true,
    elapsedMs: 0,
    maxDurationMs: 10 * 60 * 1000,
    completedPolls: 0,
    initialIntervalMs: 3000,
    maxIntervalMs: 30000,
    errorStatus: null,
  };

  it("polls with exponential backoff only while GENERATING", () => {
    expect(computeResultPollDelayMs(BASE)).toBe(3000);
    expect(computeResultPollDelayMs({ ...BASE, completedPolls: 2 })).toBe(12000);
    expect(computeResultPollDelayMs({ ...BASE, completedPolls: 10 })).toBe(30000); // capped
  });

  it("stops on terminal states, 403, and the duration bound", () => {
    expect(computeResultPollDelayMs({ ...BASE, anyGenerating: false })).toBeNull();
    expect(computeResultPollDelayMs({ ...BASE, errorStatus: 403 })).toBeNull();
    expect(computeResultPollDelayMs({ ...BASE, elapsedMs: 10 * 60 * 1000 })).toBeNull();
  });
});


describe("SP-607 R1: §10.3 Retry/Support split on the failed state", () => {
  it("shows the working Retry CTA for a user-retryable failure", () => {
    const html = renderToStaticMarkup(
      <SketchViewer state="failed" retryAvailable={true} onRetry={() => {}} />
    );
    expect(html).toContain('data-testid="sketch-retry-btn"');
    expect(html).toContain("Retry Generation");
    expect(html).not.toContain('data-testid="sketch-support-note"');
  });

  it("hides Retry and shows the support path when retries are exhausted", () => {
    const html = renderToStaticMarkup(
      <SketchViewer state="failed" retryAvailable={false} onRetry={() => {}} />
    );
    expect(html).not.toContain('data-testid="sketch-retry-btn"');
    expect(html).toContain('data-testid="sketch-support-note"');
    expect(html).toContain("contact support");
  });
});
