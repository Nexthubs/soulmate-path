"""
Canonical SoulmateReportV1 schema and content validation (DEV-SPEC §13.2; Decisions: REPORT-01, REPORT-02).

Owns the structured, versioned report content contract consumed by:
- Report persistence (SP-702): stores the validated JSON as content_json;
- Report renderer (SP-703): renders text nodes only, never raw model output;
- Report generator interface (SP-704): provider output must validate against this schema.

The structure mirrors the Figma editorial report (102:1358): H1 title, intro paragraph,
numbered sections (display label + title + body), optional point lists with optional
lead-in titles, and an optional closing line (the Figma end mark is decorative, so
`closing` stays optional content).

Decisions REPORT-01/REPORT-02 are OPEN: no production generator, model, or prompt is
implemented or implied here. This module is a pure content contract — it never authors
"spiritual reading" copy and holds no personalization logic.

Security posture: all text fields are plain prose. Markup-like or script-bearing
content is rejected at the schema boundary (not sanitized), so no executable
HTML/script can enter persistence or reach a renderer through this contract. The
renderer must additionally render text nodes only (SP-703); entity-encoded content
(e.g. "&lt;script&gt;") is inert plain text and is accepted.
"""

import re
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.core.errors import ValidationError

# The only content schema version this contract accepts. An absent field defaults here;
# an explicitly different value is rejected so persisted content_json can never drift
# from what the V1 renderer/persistence code was built against (acceptance: schema/version field).
REPORT_SCHEMA_VERSION = "v1"

_ACCEPTED_SCHEMA_VERSIONS = frozenset({REPORT_SCHEMA_VERSION})

# Markup-like content: '<' (or '</') immediately followed by a letter and closed by '>'.
# This mirrors real HTML5 tag parsing (a '<' followed by whitespace or a non-letter is
# plain text), so ordinary prose like "5 < 6" or "i <3 you" stays valid while any real
# or spoofed tag (<script>, <img onerror=...>, <iframe>, <ScRiPt>, </div>, <svg/onload=...>)
# is rejected.
_TAG_LIKE_RE = re.compile(r"</?[A-Za-z][^>]*>")

# URL schemes that execute script when a renderer ever links the text. Matched only at
# a word boundary so tokens like "notjavascript:" do not false-positive; a prose
# mention of "JavaScript:" is rejected by design — an editorial report has no reason
# to carry a script-scheme token.
_SCRIPT_SCHEME_RE = re.compile(r"\b(javascript|vbscript):", re.IGNORECASE)


class ReportValidationError(ValidationError):
    """Raised when report content violates the SoulmateReportV1 schema or content policy."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message=message, details=details or {})


def _check_plain_text(v: Optional[str], field_name: str) -> Optional[str]:
    """
    Shared content-policy check for every report text field: plain prose only.

    Rejects markup-like content and script URL schemes instead of sanitizing them,
    so the failure is visible to the caller (generation/persistence) rather than
    silently rewritten.
    """
    if v is None:
        return None
    tag = _TAG_LIKE_RE.search(v)
    if tag:
        raise ReportValidationError(
            f"Report {field_name} contains markup-like content "
            f"({tag.group(0)[:40]!r}); only plain text is allowed.",
            details={"field": field_name, "reason": "markup_like_content"},
        )
    scheme = _SCRIPT_SCHEME_RE.search(v)
    if scheme:
        raise ReportValidationError(
            f"Report {field_name} contains a script URL scheme ({scheme.group(0)!r}).",
            details={"field": field_name, "reason": "script_url_scheme"},
        )
    return v


def _require_non_blank(v: str, field_name: str) -> str:
    if not v.strip():
        raise ReportValidationError(
            f"Report {field_name} must not be blank.",
            details={"field": field_name},
        )
    return v


class SoulmateReportSectionPoint(BaseModel):
    """
    One optional point inside a section (DEV-SPEC §13.2).

    `title` is the optional bold lead-in Figma renders before the colon ("Strong → ...");
    `body` is the point text and is always required.

    Error details use the full in-report field path (points.title / points.body) so a
    rejection is diagnosable even when raised through nested validation.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )

    title: Optional[str] = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("title", "body")
    @classmethod
    def _plain_text(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _check_plain_text(v, f"points.{info.field_name}")

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, v: str) -> str:
        return _require_non_blank(v, "points.body")

    @field_validator("title")
    @classmethod
    def _title_not_blank_if_present(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _require_non_blank(v, "points.title")
        return v


class SoulmateReportSection(BaseModel):
    """One numbered editorial section (DEV-SPEC §13.2). Error details use full field paths."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )

    index: str = Field(min_length=1, max_length=16, description="Display number label, e.g. '01.'")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    points: Optional[List[SoulmateReportSectionPoint]] = Field(default=None, max_length=12)

    @field_validator("index", "title", "body")
    @classmethod
    def _plain_text(cls, v: str, info: ValidationInfo) -> str:
        return _check_plain_text(v, f"sections.{info.field_name}")

    @field_validator("index", "title", "body")
    @classmethod
    def _not_blank(cls, v: str, info: ValidationInfo) -> str:
        return _require_non_blank(v, f"sections.{info.field_name}")

    @model_validator(mode="after")
    def _normalize_points(self) -> "SoulmateReportSection":
        # An empty points list carries no information; normalize to absent so persisted
        # content_json never stores meaningless empty arrays.
        if self.points is not None and len(self.points) == 0:
            self.points = None
        return self


class SoulmateReportV1(BaseModel):
    """
    Canonical versioned Soulmate Report content (DEV-SPEC §13.2).

    - snake_case attributes (Pythonic / DB) with camelCase serialization
      (schemaVersion) matching the TypeScript interface.
    - extra="forbid": a provider payload or stored JSON carrying unknown fields is
      rejected, not silently dropped.
    - sections is a list: array order is the authoritative display order; `index`
      is a display label only and must be unique within the report.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )

    schema_version: str = Field(
        default=REPORT_SCHEMA_VERSION,
        max_length=16,
        description="Content schema version; must be 'v1' when present",
    )
    title: str = Field(min_length=1, max_length=200)
    intro: str = Field(min_length=1, max_length=4000)
    sections: List[SoulmateReportSection] = Field(min_length=1, max_length=24)
    closing: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, v: str) -> str:
        if v not in _ACCEPTED_SCHEMA_VERSIONS:
            raise ReportValidationError(
                f"Unsupported report schema version '{v}'; this contract only accepts "
                f"'{REPORT_SCHEMA_VERSION}'.",
                details={"field": "schema_version", "invalid_value": v},
            )
        return v

    @field_validator("title", "intro", "closing")
    @classmethod
    def _plain_text(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        return _check_plain_text(v, info.field_name or "text")

    @field_validator("title", "intro")
    @classmethod
    def _not_blank(cls, v: str, info: ValidationInfo) -> str:
        return _require_non_blank(v, info.field_name or "text")

    @field_validator("sections", mode="before")
    @classmethod
    def _sections_required(cls, v: Any) -> Any:
        if v is None or (isinstance(v, list) and len(v) == 0):
            raise ReportValidationError(
                "A report must contain at least one section.",
                details={"field": "sections"},
            )
        return v

    @model_validator(mode="after")
    def _validate_section_ordering(self) -> "SoulmateReportV1":
        seen = set()
        for position, section in enumerate(self.sections):
            label = section.index.strip()
            if label in seen:
                raise ReportValidationError(
                    f"Duplicate section index '{section.index}' at position {position}; "
                    "section numbering must be unique.",
                    details={
                        "field": "sections.index",
                        "duplicate_value": section.index,
                        "position": position,
                    },
                )
            seen.add(label)
        return self


def parse_soulmate_report_v1(data: Any) -> SoulmateReportV1:
    """
    Validates an arbitrary payload (e.g. generator output or stored JSON) against the
    canonical SoulmateReportV1 contract.

    Pydantic's own ValidationError is converted into the report error taxonomy so every
    schema failure surfaces the same way (HTTP 400 VALIDATION_ERROR with details).
    """
    try:
        return SoulmateReportV1.model_validate(data)
    except ReportValidationError:
        raise
    except Exception as exc:  # pydantic.ValidationError and malformed payloads
        raise ReportValidationError(
            "Payload does not conform to the SoulmateReportV1 schema.",
            details={"error": str(exc)},
        ) from exc
