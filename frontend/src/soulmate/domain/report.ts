/**
 * Canonical SoulmateReportV1 contract and runtime validation (DEV-SPEC §13.2; SP-701/SP-703;
 * Decisions: REPORT-01, REPORT-02).
 *
 * This is the frontend home of the versioned report content contract — the TypeScript
 * mirror of `backend/app/soulmate/domain/report.py`. The canonical camelCase shape
 * matches what `GET /api/soulmate/artifacts/report` serves (SP-702), which is already
 * validated server-side and re-validated on every read.
 *
 * `parseSoulmateReportV1` is the renderer-side defense in depth (SP-703 acceptance:
 * "renderer consumes only validated ReportV1"): it re-checks the V1 structure, the
 * schema version, and the plain-text content policy (markup-like / script-bearing
 * text rejected) before any report payload reaches ReportRenderer. The backend owns
 * the length caps, so they are intentionally NOT re-enforced here — structure,
 * version, and executable-content rejection are the renderer-safety-relevant rules.
 *
 * REPORT-01/REPORT-02 remain OPEN: this module authors no reading content and holds
 * no personalization logic.
 */

/** The only report content schema version this contract accepts (mirrors the backend). */
export const REPORT_SCHEMA_VERSION = "v1" as const;

export interface SoulmateReportSectionPoint {
  /** Optional bold lead-in Figma renders before the colon ("Strong → ..."). */
  title?: string;
  body: string;
}

export interface SoulmateReportSection {
  /** Display number label, e.g. "01." — unique within the report; array order is display order. */
  index: string;
  title: string;
  body: string;
  points?: SoulmateReportSectionPoint[];
}

export interface SoulmateReportV1 {
  /** Content schema version; only "v1" is produced/accepted (SP-701 contract). */
  schemaVersion: string;
  title: string;
  intro: string;
  sections: SoulmateReportSection[];
  closing?: string;
}

/** Raised when a payload does not conform to the SoulmateReportV1 contract/content policy. */
export class ReportValidationError extends Error {
  constructor(
    message: string,
    public readonly field?: string,
  ) {
    super(message);
    this.name = "ReportValidationError";
  }
}

// Mirrors backend/app/soulmate/domain/report.py: a real (or spoofed) HTML5 tag is
// '<' (or '</') immediately followed by a letter and closed by '>'. Ordinary prose
// like "5 < 6", "i <3 you", or "a<b" (no closing '>') stays valid.
const TAG_LIKE_RE = /<\/?[A-Za-z][^>]*>/;

// Script URL schemes that execute when a renderer ever links the text (word-boundary
// anchored, case-insensitive — mirrors the backend policy).
const SCRIPT_SCHEME_RE = /\b(javascript|vbscript):/i;

const MAX_SECTIONS = 24;
const MAX_POINTS_PER_SECTION = 12;

function assertPlainText(value: string, field: string): void {
  if (TAG_LIKE_RE.test(value)) {
    throw new ReportValidationError(
      `Report ${field} contains markup-like content; only plain text is allowed.`,
      field,
    );
  }
  const scheme = SCRIPT_SCHEME_RE.exec(value);
  if (scheme) {
    throw new ReportValidationError(
      `Report ${field} contains a script URL scheme (${scheme[0]}).`,
      field,
    );
  }
}

function assertNonBlankString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new ReportValidationError(`Report ${field} must be a non-empty string.`, field);
  }
  return value;
}

function parseSectionPoint(raw: unknown, field: string): SoulmateReportSectionPoint {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new ReportValidationError(`Report ${field} must be an object.`, field);
  }
  const point = raw as Record<string, unknown>;
  const body = assertNonBlankString(point.body, `${field}.body`);
  assertPlainText(body, `${field}.body`);
  const parsed: SoulmateReportSectionPoint = { body };
  if (point.title !== undefined && point.title !== null) {
    const title = assertNonBlankString(point.title, `${field}.title`);
    assertPlainText(title, `${field}.title`);
    parsed.title = title;
  }
  return parsed;
}

function parseSection(raw: unknown, position: number): SoulmateReportSection {
  const field = `sections[${position}]`;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new ReportValidationError(`Report ${field} must be an object.`, field);
  }
  const section = raw as Record<string, unknown>;
  const index = assertNonBlankString(section.index, `${field}.index`);
  assertPlainText(index, `${field}.index`);
  const title = assertNonBlankString(section.title, `${field}.title`);
  assertPlainText(title, `${field}.title`);
  const body = assertNonBlankString(section.body, `${field}.body`);
  assertPlainText(body, `${field}.body`);

  const parsed: SoulmateReportSection = { index, title, body };
  if (section.points !== undefined && section.points !== null) {
    if (!Array.isArray(section.points)) {
      throw new ReportValidationError(`Report ${field}.points must be a list.`, `${field}.points`);
    }
    if (section.points.length > MAX_POINTS_PER_SECTION) {
      throw new ReportValidationError(
        `Report ${field}.points exceeds the maximum of ${MAX_POINTS_PER_SECTION}.`,
        `${field}.points`,
      );
    }
    // An empty points list is normalized to absent (mirrors the backend).
    if (section.points.length > 0) {
      parsed.points = section.points.map((p, i) => parseSectionPoint(p, `${field}.points[${i}]`));
    }
  }
  return parsed;
}

/**
 * Validates an arbitrary payload against the canonical SoulmateReportV1 contract and
 * returns the normalized report safe for rendering.
 *
 * Accepts the backend's exact camelCase output. Unknown extra fields are ignored
 * (forward-compatible); absent schemaVersion defaults to "v1" (mirrors the backend);
 * an explicit non-"v1" version is rejected. Unknown fields never reach the renderer
 * because the renderer reads only the validated, known fields returned here.
 */
export function parseSoulmateReportV1(data: unknown): SoulmateReportV1 {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new ReportValidationError("Report payload must be an object.");
  }
  const raw = data as Record<string, unknown>;

  let schemaVersion: SoulmateReportV1["schemaVersion"] = REPORT_SCHEMA_VERSION;
  if (raw.schemaVersion !== undefined && raw.schemaVersion !== null) {
    if (raw.schemaVersion !== REPORT_SCHEMA_VERSION) {
      throw new ReportValidationError(
        `Unsupported report schema version '${String(raw.schemaVersion)}'; this contract only accepts '${REPORT_SCHEMA_VERSION}'.`,
        "schemaVersion",
      );
    }
    schemaVersion = raw.schemaVersion;
  }

  const title = assertNonBlankString(raw.title, "title");
  assertPlainText(title, "title");
  const intro = assertNonBlankString(raw.intro, "intro");
  assertPlainText(intro, "intro");

  if (!Array.isArray(raw.sections) || raw.sections.length === 0) {
    throw new ReportValidationError("A report must contain at least one section.", "sections");
  }
  if (raw.sections.length > MAX_SECTIONS) {
    throw new ReportValidationError(
      `Report exceeds the maximum of ${MAX_SECTIONS} sections.`,
      "sections",
    );
  }
  const sections = raw.sections.map(parseSection);

  const seenIndexes = new Set<string>();
  for (const section of sections) {
    const label = section.index.trim();
    if (seenIndexes.has(label)) {
      throw new ReportValidationError(
        `Duplicate section index '${section.index}'; section numbering must be unique.`,
        "sections.index",
      );
    }
    seenIndexes.add(label);
  }

  const report: SoulmateReportV1 = { schemaVersion, title, intro, sections };
  if (raw.closing !== undefined && raw.closing !== null) {
    if (typeof raw.closing !== "string") {
      throw new ReportValidationError("Report closing must be a string.", "closing");
    }
    // Cross-stack parity (M5 review M-02): a blank optional closing carries no
    // content and normalizes to absent — exactly what the backend contract does —
    // so backend-serialized payloads always pass the renderer gate. Markup/script
    // rejection still applies to any non-blank closing.
    if (raw.closing.trim()) {
      assertPlainText(raw.closing, "closing");
      report.closing = raw.closing;
    }
  }
  return report;
}

/**
 * Non-throwing variant for render guards: true when the payload fully conforms.
 */
export function isSoulmateReportV1(data: unknown): data is SoulmateReportV1 {
  try {
    parseSoulmateReportV1(data);
    return true;
  } catch {
    return false;
  }
}
