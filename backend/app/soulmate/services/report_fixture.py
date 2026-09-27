"""
Canonical report mock fixture (SP-705; DEV-SPEC §13.2–13.3; Decisions: REPORT-01, REPORT-02).

**This module is test fixture content only — it is never production report copy.**
Every payload is unmistakably labeled (`[MOCK]` title, "Not a Real Reading"), makes
no personalized or psychological claims, and points at the open REPORT-01/REPORT-02
decisions that keep production generation disabled.

Single source of truth for mock report content across the M5 scaffold:
- `MockReportProvider` (SP-704) renders `build_mock_report(...)` so the mock
  provider and every test use identical, deterministic content;
- `MOCK_REPORT_JSON` is the profile-independent static camelCase payload for
  persistence/E2E seeding and mirrors `frontend/src/soulmate/fixtures/report.ts`;
- with a normalized profile, `build_mock_report` echoes a few §7 fields so E2E can
  prove the §13.3 input contract (QUIZ-01 respected: Q03, never Q02).

Production report copy is an unresolved REPORT-02 decision and must never be added
to this module.
"""

from typing import Optional

from app.soulmate.domain.profile import SoulmateProfileV1
from app.soulmate.domain.report import SoulmateReportV1, parse_soulmate_report_v1

MOCK_REPORT_TITLE = "[MOCK] Soulmate Report — Test Fixture, Not a Real Reading"
MOCK_REPORT_INTRO = (
    "Deterministic mock fixture content used only for renderer and E2E testing. "
    "Production report generation stays disabled (REPORT-01/REPORT-02)."
)
MOCK_REPORT_CLOSING = "[MOCK] End of test fixture."

# Static, profile-independent payload (camelCase, ReportV1-conformant). Kept in sync
# with frontend/src/soulmate/fixtures/report.ts (MOCK_REPORT_FIXTURE).
MOCK_REPORT_JSON: dict = {
    "schemaVersion": "v1",
    "title": MOCK_REPORT_TITLE,
    "intro": MOCK_REPORT_INTRO,
    "sections": [
        {
            "index": "01.",
            "title": "Fixture Purpose (Non-Production)",
            "body": (
                "This section lets persistence, retrieval, and renderer tests verify "
                "the ReportV1 contract end to end without any AI provider call."
            ),
            "points": [
                {
                    "title": "Deterministic",
                    "body": "Identical inputs produce identical structure; no external service is called.",
                },
                {
                    "title": "Clearly Non-Production",
                    "body": "The [MOCK] label and REPORT-01/REPORT-02 references mark this as test content.",
                },
            ],
        },
        {
            "index": "02.",
            "title": "Schema Conformance Check",
            "body": (
                "Optional points, a closing line, and ordered numbered sections are all "
                "present so the renderer covers the full DEV-SPEC §13.2 structure."
            ),
        },
    ],
    "closing": MOCK_REPORT_CLOSING,
}


def build_mock_report(profile: Optional[SoulmateProfileV1] = None) -> SoulmateReportV1:
    """
    Builds the canonical mock report, validated against the ReportV1 contract.

    Without a profile the static fixture is returned. With a normalized
    `SoulmateProfileV1`, section 01 becomes an input-contract echo so E2E tests can
    verify the provider consumed the normalized profile (§13.3).
    """
    if profile is None:
        return parse_soulmate_report_v1(MOCK_REPORT_JSON)

    payload = {
        **MOCK_REPORT_JSON,
        "sections": [
            {
                "index": "01.",
                "title": "Mock Input Echo (Non-Production)",
                "body": (
                    f"Normalized profile input received: preferred partner gender "
                    f"'{profile.preferred_partner_gender}', age range "
                    f"'{profile.preferred_partner_age_range}', key quality "
                    f"'{profile.key_soulmate_quality}'."
                ),
                "points": [
                    {
                        "title": "Deterministic",
                        "body": "Identical inputs produce identical structure; no external service is called.",
                    }
                ],
            },
            *MOCK_REPORT_JSON["sections"][1:],
        ],
    }
    return parse_soulmate_report_v1(payload)
