/**
 * Canonical report mock fixtures (SP-705; DEV-SPEC §13.2–13.3; Decisions: REPORT-01, REPORT-02).
 *
 * **Test fixture content only — never production report copy.** `MOCK_REPORT_FIXTURE`
 * mirrors the backend canonical payload (`backend/app/soulmate/services/report_fixture.py`,
 * `MOCK_REPORT_JSON`) so persistence/E2E and renderer tests exercise identical
 * content. Every fixture is unmistakably labeled (`[MOCK]`, "Not a Real Reading")
 * and points at the REPORT-01/REPORT-02 decisions that keep production generation
 * disabled. `DEFAULT_REPORT_FIXTURE` (components/report) remains the Figma 102:1358
 * canonical preview fixture.
 */

import type { SoulmateReportV1 } from "@/soulmate/domain/report";

export const MOCK_REPORT_TITLE = "[MOCK] Soulmate Report — Test Fixture, Not a Real Reading";
export const MOCK_REPORT_INTRO =
  "Deterministic mock fixture content used only for renderer and E2E testing. " +
  "Production report generation stays disabled (REPORT-01/REPORT-02).";
export const MOCK_REPORT_CLOSING = "[MOCK] End of test fixture.";

export const MOCK_REPORT_FIXTURE: SoulmateReportV1 = {
  schemaVersion: "v1",
  title: MOCK_REPORT_TITLE,
  intro: MOCK_REPORT_INTRO,
  sections: [
    {
      index: "01.",
      title: "Fixture Purpose (Non-Production)",
      body:
        "This section lets persistence, retrieval, and renderer tests verify " +
        "the ReportV1 contract end to end without any AI provider call.",
      points: [
        {
          title: "Deterministic",
          body: "Identical inputs produce identical structure; no external service is called.",
        },
        {
          title: "Clearly Non-Production",
          body: "The [MOCK] label and REPORT-01/REPORT-02 references mark this as test content.",
        },
      ],
    },
    {
      index: "02.",
      title: "Schema Conformance Check",
      body:
        "Optional points, a closing line, and ordered numbered sections are all " +
        "present so the renderer covers the full DEV-SPEC §13.2 structure.",
    },
  ],
  closing: MOCK_REPORT_CLOSING,
};
