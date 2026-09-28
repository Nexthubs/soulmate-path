/**
 * Mock fixture tests (SP-705; Decisions: REPORT-01, REPORT-02).
 * Verifies the canonical mock fixtures conform to the ReportV1 contract, stay
 * unmistakably non-production, and render safely through the ReportRenderer gate.
 */
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ReportRenderer, DEFAULT_REPORT_FIXTURE } from "../src/soulmate/components/report";
import { parseSoulmateReportV1 } from "../src/soulmate/domain/report";
import {
  MOCK_REPORT_FIXTURE,
  MOCK_REPORT_INTRO,
  MOCK_REPORT_TITLE,
} from "../src/soulmate/fixtures/report";

// Mock next/navigation (same setup as report-renderer.test.tsx)
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
}));

describe("SP-705: canonical report mock fixture", () => {
  it("is unmistakably non-production content", () => {
    expect(MOCK_REPORT_TITLE.startsWith("[MOCK]")).toBe(true);
    expect(MOCK_REPORT_TITLE).toContain("Not a Real Reading");
    expect(MOCK_REPORT_INTRO).toContain("mock fixture");
    expect(MOCK_REPORT_INTRO).toContain("stays disabled");
    expect(MOCK_REPORT_FIXTURE.closing?.startsWith("[MOCK]")).toBe(true);
  });

  it("conforms to the ReportV1 contract (backend mirror payload)", () => {
    const parsed = parseSoulmateReportV1(MOCK_REPORT_FIXTURE);
    expect(parsed.schemaVersion).toBe("v1");
    expect(parsed.sections.map((s) => s.index)).toEqual(["01.", "02."]);
    expect(parsed.sections[0].points?.length).toBeGreaterThan(0);
    expect(parsed.closing).toBeTruthy();
  });

  it("covers the full §13.2 structure: points and closing render through the gate", () => {
    const html = renderToStaticMarkup(<ReportRenderer report={MOCK_REPORT_FIXTURE} />);
    expect(html).toContain('data-testid="report-title"');
    expect(html).toContain("[MOCK] Soulmate Report");
    expect(html).toContain('data-testid="section-points-list"');
    expect(html).toContain("Deterministic");
    expect(html).toContain('data-testid="report-closing"');
    expect(html).not.toContain('data-testid="report-invalid-fallback"');
  });

  it("SP-108 Figma fixture also conforms to the validated contract", () => {
    const parsed = parseSoulmateReportV1(DEFAULT_REPORT_FIXTURE);
    expect(parsed.schemaVersion).toBe("v1");
    expect(parsed.sections.length).toBe(3);
  });
});
