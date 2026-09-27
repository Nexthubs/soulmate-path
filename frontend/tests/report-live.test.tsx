/**
 * Live Report page tests (M5 review H-01 remediation; SP-702/SP-703; Decisions: TIME-01, RECOVERY-01).
 *
 * Acceptance criteria under test:
 * - §10.3 mapping: LOCKED→route-to-Result, READY→preparing, GENERATING→loading,
 *   COMPLETED→rendered validated content, FAILED→support (server status is the authority);
 * - the page renders the STORED, server-validated content via the SP-703 gate, and
 *   a COMPLETED status without content degrades to support (never the Figma fixture);
 * - report API client: correct endpoint/credentials handling;
 * - the fixture preview mode remains a dev-only opt-in.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SoulmateReportPage from "../src/app/soulmate/report/page";
import { deriveReportViewState, useReportStatus } from "../src/soulmate/hooks/useReportStatus";
import { getReportStatus } from "../src/soulmate/api/report";
import { MOCK_REPORT_FIXTURE } from "../src/soulmate/fixtures/report";
import { ClientConfig } from "../src/soulmate/config";

const routerMock = vi.hoisted(() => ({ replace: vi.fn() }));
const searchParamsMock = vi.hoisted(() => ({
  current: new Map<string, string>(),
}));
const guardMock = vi.hoisted(() => ({
  current: {
    allowed: null as boolean | null,
    error: null as string | null,
    verdict: null as { redirect_to?: string; reason?: string } | null,
    retry: vi.fn(),
  },
}));
const reportHookMock = vi.hoisted(() => ({
  current: {
    data: null as
      | {
          server_time: string;
          report: { status: string | null; availability?: string; generation?: string };
          content: unknown;
        }
      | null,
    isLoading: true,
    error: null as string | null,
    errorStatus: null as number | null,
    refresh: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: routerMock.replace }),
  useSearchParams: () => ({
    get: (key: string) => searchParamsMock.current.get(key) ?? null,
  }),
}));

vi.mock("@/soulmate/hooks/useRouteGuard", () => ({
  useRouteGuard: () => guardMock.current,
}));

vi.mock("@/soulmate/hooks/useReportStatus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/soulmate/hooks/useReportStatus")>();
  return { ...actual, useReportStatus: () => reportHookMock.current };
});

const mockConfig: ClientConfig = {
  appBaseUrl: "http://localhost:3000",
  apiBaseUrl: "http://localhost:8000/api/soulmate",
  paypalClientId: "mock_client_id",
  currency: "USD",
  introPrice: "19.00",
  regularPrice: "29.00",
};

describe("SP-607-pattern: deriveReportViewState (§10.3 mapping)", () => {
  it("maps every server-derived combined status to the correct view state", () => {
    expect(deriveReportViewState("LOCKED")).toBe("locked");
    expect(deriveReportViewState("READY")).toBe("ready");
    expect(deriveReportViewState("GENERATING")).toBe("loading");
    expect(deriveReportViewState("COMPLETED")).toBe("completed");
    expect(deriveReportViewState("FAILED")).toBe("failed");
  });

  it("returns null for unknown/unloaded status", () => {
    expect(deriveReportViewState(null)).toBeNull();
    expect(deriveReportViewState(undefined)).toBeNull();
    expect(deriveReportViewState("SOMETHING_ELSE")).toBeNull();
  });
});

describe("SP-702 client: getReportStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hits GET /artifacts/report with credentials and returns the parsed payload", async () => {
    const payload = {
      server_time: "2026-09-27T00:00:00Z",
      report: { status: "COMPLETED", availability: "UNLOCKED", generation: "COMPLETED" },
      content: MOCK_REPORT_FIXTURE,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await getReportStatus("sess_123", mockConfig);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/soulmate/artifacts/report?session_id=sess_123",
      expect.objectContaining({ method: "GET", credentials: "include" })
    );
    expect(res.content?.title).toBe(MOCK_REPORT_FIXTURE.title);
  });

  it("throws a parsed API error for non-2xx responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "FORBIDDEN_OWNERSHIP" }), { status: 403 })
      )
    );
    await expect(getReportStatus(undefined, mockConfig)).rejects.toMatchObject({
      status: 403,
    });
  });
});

describe("M5-H01: live report page state machine", () => {
  beforeEach(() => {
    routerMock.replace.mockClear();
    searchParamsMock.current = new Map();
    guardMock.current = {
      allowed: null,
      error: null,
      verdict: null,
      retry: vi.fn(),
    };
    reportHookMock.current = {
      data: null,
      isLoading: true,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
  });

  it("live loading: shows the neutral loading card before the authoritative state arrives", () => {
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain("Loading report");
    expect(html).not.toContain("[MOCK]");
  });

  it("live READY: shows the create CTA (on_demand, SP-706)", () => {
    reportHookMock.current = {
      data: {
        server_time: "2026-09-27T00:00:00Z",
        report: { status: "READY", availability: "UNLOCKED", generation: "NOT_STARTED" },
        content: null,
      },
      isLoading: false,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-ready-state"');
    expect(html).toContain('data-testid="report-ready-cta"');
    expect(html).toContain("Create My Report");
  });

  it("live FAILED: shows the retry CTA and support copy", () => {
    reportHookMock.current = {
      data: {
        server_time: "2026-09-27T00:00:00Z",
        report: { status: "FAILED", availability: "UNLOCKED", generation: "FAILED" },
        content: null,
      },
      isLoading: false,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-failed-state"');
    expect(html).toContain('data-testid="report-failed-cta"');
    expect(html).toContain("Report Unavailable");
  });

  it("live COMPLETED: renders the stored validated content through the renderer gate", () => {
    reportHookMock.current = {
      data: {
        server_time: "2026-09-27T00:00:00Z",
        report: { status: "COMPLETED", availability: "UNLOCKED", generation: "COMPLETED" },
        content: MOCK_REPORT_FIXTURE,
      },
      isLoading: false,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-title"');
    expect(html).toContain("[MOCK] Soulmate Report");
    expect(html).not.toContain('data-testid="report-invalid-fallback"');
    expect(html).not.toContain("Releasing the Fear of Being Alone"); // Figma fixture never substitutes
  });

  it("live COMPLETED without content degrades to support (never renders the fixture)", () => {
    reportHookMock.current = {
      data: {
        server_time: "2026-09-27T00:00:00Z",
        report: { status: "COMPLETED", availability: "UNLOCKED", generation: "COMPLETED" },
        content: null,
      },
      isLoading: false,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-failed-state"');
    expect(html).not.toContain("Releasing the Fear of Being Alone");
  });

  it("live COMPLETED with contract-violating content falls into the renderer gate fallback", () => {
    reportHookMock.current = {
      data: {
        server_time: "2026-09-27T00:00:00Z",
        report: { status: "COMPLETED", availability: "UNLOCKED", generation: "COMPLETED" },
        content: { schemaVersion: "v1", title: "<script>x</script>", intro: "i", sections: [] },
      },
      isLoading: false,
      error: null,
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-invalid-fallback"');
    expect(html).not.toContain("<script>");
  });

  it("live fetch error without data: read-only retry card", () => {
    reportHookMock.current = {
      data: null,
      isLoading: false,
      error: "Network error",
      errorStatus: null,
      refresh: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-refresh-read"');
    expect(html).toContain("Try Again");
  });

  it("guard denial: shows the entitlement card instead of any report content", () => {
    // Dev mode requires the explicit ?guard=true opt-in (production guards by default).
    searchParamsMock.current = new Map([["guard", "true"]]);
    guardMock.current = {
      allowed: false,
      error: null,
      verdict: { redirect_to: "/soulmate/subscribe", reason: "Payment required" },
      retry: vi.fn(),
    };
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain("Soulmate Report Locked");
    expect(html).not.toContain('data-testid="report-title"');
  });

  it("fixture preview (dev opt-in) keeps the SP-108 banner and toolbar", () => {
    searchParamsMock.current = new Map([["fixture", "true"]]);
    const html = renderToStaticMarkup(<SoulmateReportPage />);
    expect(html).toContain('data-testid="report-fixture-banner"');
    expect(html).toContain('data-testid="report-fixture-toolbar"');
  });
});

// Keep the hook import referenced for type checking of the mock shape.
void useReportStatus;
