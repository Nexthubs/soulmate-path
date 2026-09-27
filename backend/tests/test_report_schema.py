"""
Tests for the canonical SoulmateReportV1 schema (DEV-SPEC §13.2; SP-701; Decisions: REPORT-01, REPORT-02).

Covers:
- Figma structure coverage: title, intro, ordered sections with index/title/body,
  optional points (optional lead-in title + required body), optional closing,
  and the schema/version field;
- versioning: default 'v1', rejection of unknown versions;
- plain-text content policy: markup-like / script-bearing content rejected on every
  text field while inert prose ("<3", "5 < 6", entity-encoded text) stays valid;
- structural integrity: unique section labels, preserved array order, extra-field
  rejection, length bounds, error taxonomy (core ValidationError -> HTTP 400).
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.soulmate.domain.report import (
    REPORT_SCHEMA_VERSION,
    ReportValidationError,
    SoulmateReportSection,
    SoulmateReportSectionPoint,
    SoulmateReportV1,
    parse_soulmate_report_v1,
)


def _minimal_payload(**overrides):
    payload = {
        "title": "Your Soulmate Report",
        "intro": "Before two souls cross paths, they rendezvous energetically.",
        "sections": [
            {
                "index": "01.",
                "title": "Releasing the Fear of Being Alone",
                "body": "Real alignment begins the moment you cherish your solitude.",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _full_payload(**overrides):
    payload = {
        "schema_version": "v1",
        "title": "Your Soulmate Report",
        "intro": "Before two souls cross paths in the physical realm, they rendezvous energetically.",
        "sections": [
            {
                "index": "01.",
                "title": "Releasing the Fear of Being Alone",
                "body": "Desperation carries an emotional resonance of scarcity.",
            },
            {
                "index": "02.",
                "title": "Tuning Your Energetic Signature",
                "body": "Start grounding these three daily rituals:",
                "points": [
                    {"title": "Morning Heart Opening", "body": "3 minutes of slow somatic breathing."},
                    {"body": "Mentally dissolving cords tied to past lovers."},
                ],
            },
        ],
        "closing": "Trust the timing of your life.",
    }
    payload.update(overrides)
    return payload


class TestStructureCoverage:
    def test_full_report_with_points_and_closing_is_valid(self):
        report = SoulmateReportV1.model_validate(_full_payload())
        assert report.title == "Your Soulmate Report"
        assert len(report.sections) == 2
        assert report.sections[1].points is not None
        assert report.sections[1].points[0].title == "Morning Heart Opening"
        assert report.sections[1].points[1].title is None
        assert report.closing == "Trust the timing of your life."

    def test_minimal_report_without_optional_fields_is_valid(self):
        report = SoulmateReportV1.model_validate(_minimal_payload())
        assert report.closing is None
        assert report.sections[0].points is None

    def test_camel_case_serialization_exposes_schema_version(self):
        report = SoulmateReportV1.model_validate(_full_payload())
        dumped = report.model_dump(by_alias=True, exclude_none=True)
        assert dumped["schemaVersion"] == "v1"
        assert "schema_version" not in dumped

    def test_schema_version_defaults_to_v1_when_absent(self):
        payload = _minimal_payload()
        assert "schema_version" not in payload
        report = SoulmateReportV1.model_validate(payload)
        assert report.schema_version == REPORT_SCHEMA_VERSION

    def test_unknown_schema_version_is_rejected(self):
        with pytest.raises(ReportValidationError) as exc_info:
            SoulmateReportV1.model_validate(_minimal_payload(schema_version="v2"))
        assert exc_info.value.details["field"] == "schema_version"

    def test_missing_required_top_level_fields_are_rejected(self):
        for missing in ("title", "intro", "sections"):
            payload = _minimal_payload()
            del payload[missing]
            with pytest.raises((ReportValidationError, PydanticValidationError)):
                SoulmateReportV1.model_validate(payload)

    def test_empty_sections_list_is_rejected(self):
        with pytest.raises(ReportValidationError) as exc_info:
            SoulmateReportV1.model_validate(_minimal_payload(sections=[]))
        assert exc_info.value.details["field"] == "sections"

    def test_report_requires_at_least_one_section(self):
        payload = _minimal_payload()
        del payload["sections"]
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportV1.model_validate(payload)


class TestSectionStructure:
    def test_array_order_is_authoritative_display_order(self):
        payload = _minimal_payload(
            sections=[
                {"index": "03.", "title": "Third", "body": "Body three."},
                {"index": "01.", "title": "First", "body": "Body one."},
            ]
        )
        report = SoulmateReportV1.model_validate(payload)
        # Order is preserved exactly as given; index is a display label, never re-sorted.
        assert [s.index for s in report.sections] == ["03.", "01."]

    def test_duplicate_section_index_is_rejected(self):
        sections = [
            {"index": "01.", "title": "A", "body": "Body a."},
            {"index": "01.", "title": "B", "body": "Body b."},
        ]
        with pytest.raises(ReportValidationError) as exc_info:
            SoulmateReportV1.model_validate(_minimal_payload(sections=sections))
        assert exc_info.value.details["duplicate_value"] == "01."

    def test_blank_section_fields_are_rejected(self):
        for field in ("index", "title", "body"):
            section = {"index": "01.", "title": "T", "body": "B."}
            section[field] = "   "
            with pytest.raises((ReportValidationError, PydanticValidationError)):
                SoulmateReportSection.model_validate(section)

    def test_blank_top_level_fields_are_rejected(self):
        for field in ("title", "intro"):
            with pytest.raises((ReportValidationError, PydanticValidationError)):
                SoulmateReportV1.model_validate(_minimal_payload(**{field: "   "}))

    def test_empty_points_list_is_normalized_to_absent(self):
        section = SoulmateReportSection.model_validate(
            {"index": "01.", "title": "T", "body": "B.", "points": []}
        )
        assert section.points is None

    def test_point_requires_body_and_allows_optional_title(self):
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportSectionPoint.model_validate({"title": "Only a title"})
        point = SoulmateReportSectionPoint.model_validate({"body": "Just a body."})
        assert point.title is None

    def test_blank_point_body_is_rejected(self):
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportSectionPoint.model_validate({"body": "  \n  "})


class TestPlainContentPolicy:
    @pytest.mark.parametrize(
        "malicious",
        [
            "<script>alert(1)</script>",
            "<ScRiPt>alert(1)</ScRiPt>",
            "<img src=x onerror=alert(1)>",
            "<iframe src='https://evil.example'></iframe>",
            "</div>trusted text",
            "<svg/onload=alert(1)>",
            "<a href=\"javascript:alert(1)\">click</a>",
            "javascript:alert(1)",
            "JaVaScRiPt:void(0)",
            "vbscript:msgbox(1)",
        ],
    )
    @pytest.mark.parametrize(
        "field_target",
        ["title", "intro", "closing", "section_title", "section_body", "point_title", "point_body"],
    )
    def test_markup_and_script_content_is_rejected_on_every_text_field(self, malicious, field_target):
        payload = _full_payload()
        if field_target == "title":
            payload["title"] = malicious
        elif field_target == "intro":
            payload["intro"] = malicious
        elif field_target == "closing":
            payload["closing"] = malicious
        elif field_target == "section_title":
            payload["sections"][0]["title"] = malicious
        elif field_target == "section_body":
            payload["sections"][0]["body"] = malicious
        elif field_target == "point_title":
            payload["sections"][1]["points"][0]["title"] = malicious
        elif field_target == "point_body":
            payload["sections"][1]["points"][0]["body"] = malicious

        with pytest.raises(ReportValidationError) as exc_info:
            SoulmateReportV1.model_validate(payload)
        assert exc_info.value.details["field"].startswith(("sections", "points", field_target.split("_")[0]))

    @pytest.mark.parametrize(
        "short_malicious",
        [
            "<b>",
            "</b>",
            "<s>x",
            "<img>",
            "javascript:",
            "JaVaScRiPt:",
            "vbscript:",
        ],
    )
    def test_markup_and_script_content_is_rejected_on_section_index(self, short_malicious):
        # index has a tight display-label length cap, so index-specific payloads stay
        # short enough to reach the content policy instead of tripping the length bound.
        payload = _full_payload()
        payload["sections"][0]["index"] = short_malicious
        with pytest.raises(ReportValidationError) as exc_info:
            SoulmateReportV1.model_validate(payload)
        assert exc_info.value.details["field"] == "sections.index"
        assert exc_info.value.details["reason"] in ("markup_like_content", "script_url_scheme")

    @pytest.mark.parametrize(
        "safe_prose",
        [
            "i <3 you more than yesterday",
            "5 < 6 and 7 > 5",
            "Tom & Jerry remain friends",
            "&lt;script&gt;alert(1)&lt;/script&gt;",  # entity-encoded: inert plain text
            "the angle bracket pair a<b has no closing tag",
            "Choose hope: not despair.",
        ],
    )
    def test_inert_prose_is_accepted(self, safe_prose):
        report = SoulmateReportV1.model_validate(
            _full_payload(title=safe_prose, intro=safe_prose, closing=safe_prose)
        )
        assert report.title == safe_prose

    def test_rejection_is_refusal_not_sanitization(self):
        with pytest.raises(ReportValidationError) as exc_info:
            parse_soulmate_report_v1(_minimal_payload(title="Hi <script>alert(1)</script>"))
        assert exc_info.value.details["reason"] == "markup_like_content"


class TestContractBoundaries:
    def test_extra_fields_are_rejected(self):
        payload = _minimal_payload(generated_by="some-model")
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportV1.model_validate(payload)

    def test_over_long_fields_are_rejected(self):
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportV1.model_validate(_minimal_payload(title="x" * 201))
        with pytest.raises((ReportValidationError, PydanticValidationError)):
            SoulmateReportV1.model_validate(_minimal_payload(intro="x" * 4001))

    def test_non_string_body_is_rejected(self):
        payload = _minimal_payload()
        payload["sections"][0]["body"] = 12345
        with pytest.raises(ReportValidationError):
            parse_soulmate_report_v1(payload)

    def test_parse_wraps_arbitrary_broken_payloads(self):
        for broken in (None, [], "just a string", {"title": 1}):
            with pytest.raises(ReportValidationError):
                parse_soulmate_report_v1(broken)

    def test_parse_round_trips_valid_payload(self):
        report = parse_soulmate_report_v1(_full_payload())
        again = parse_soulmate_report_v1(report.model_dump(by_alias=True))
        assert again == report

    def test_report_error_is_core_validation_error(self):
        # Error taxonomy: report schema failures must surface as HTTP 400 VALIDATION_ERROR.
        assert issubclass(ReportValidationError, ValidationError)
