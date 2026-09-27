/**
 * Domain validation tests for the canonical SoulmateReportV1 contract (SP-703;
 * mirrors backend/tests/test_report_schema.py policy; DEV-SPEC §13.2; REPORT-01/02).
 */
import { describe, expect, it } from "vitest";
import {
  REPORT_SCHEMA_VERSION,
  ReportValidationError,
  isSoulmateReportV1,
  parseSoulmateReportV1,
} from "../src/soulmate/domain/report";

function validPayload(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "v1",
    title: "Your Soulmate Report",
    intro: "Before two souls cross paths, they rendezvous energetically.",
    sections: [
      {
        index: "01.",
        title: "Releasing the Fear of Being Alone",
        body: "Real alignment begins the moment you cherish your solitude.",
        points: [{ title: "Morning Heart Opening", body: "3 minutes of slow somatic breathing." }],
      },
      {
        index: "02.",
        title: "Tuning Your Energetic Signature",
        body: "Start grounding these three daily rituals:",
      },
    ],
    closing: "Trust the timing of your life.",
    ...overrides,
  };
}

describe("REPORT_SCHEMA_VERSION", () => {
  it("pins the accepted content schema version to v1", () => {
    expect(REPORT_SCHEMA_VERSION).toBe("v1");
  });
});

describe("parseSoulmateReportV1 — valid payloads", () => {
  it("parses a full report and preserves section order and points", () => {
    const report = parseSoulmateReportV1(validPayload());
    expect(report.schemaVersion).toBe("v1");
    expect(report.sections.map((s) => s.index)).toEqual(["01.", "02."]);
    expect(report.sections[0].points?.[0].title).toBe("Morning Heart Opening");
    expect(report.closing).toBe("Trust the timing of your life.");
  });

  it("defaults an absent schemaVersion to v1 (mirrors the backend)", () => {
    const payload = validPayload();
    delete (payload as { schemaVersion?: string }).schemaVersion;
    expect(parseSoulmateReportV1(payload).schemaVersion).toBe("v1");
  });

  it("accepts inert prose and entity-encoded text (plain-text renderer policy)", () => {
    const report = parseSoulmateReportV1(
      validPayload({
        title: "i <3 you",
        intro: "5 < 6 and 7 > 5",
        closing: "&lt;script&gt;alert(1)&lt;/script&gt;",
      })
    );
    expect(report.title).toBe("i <3 you");
  });

  it("ignores unknown extra fields (forward-compatible) and normalizes empty points", () => {
    const payload = validPayload({
      generatedBy: "some-provider",
    }) as Record<string, unknown> & { sections: Array<Record<string, unknown>> };
    payload.sections[0].points = [];
    const report = parseSoulmateReportV1(payload);
    expect(report.sections[0].points).toBeUndefined();
  });
});

describe("parseSoulmateReportV1 — structural rejection", () => {
  it("rejects non-object payloads", () => {
    for (const broken of [null, undefined, "string", 42, []]) {
      expect(() => parseSoulmateReportV1(broken)).toThrow(ReportValidationError);
    }
  });

  it("rejects missing or blank required fields", () => {
    for (const field of ["title", "intro"]) {
      const missing = validPayload();
      delete (missing as Record<string, unknown>)[field];
      expect(() => parseSoulmateReportV1(missing)).toThrow(ReportValidationError);

      const blank = validPayload({ [field]: "   " });
      expect(() => parseSoulmateReportV1(blank)).toThrow(ReportValidationError);
    }
  });

  it("rejects empty, missing, or oversized section lists", () => {
    expect(() => parseSoulmateReportV1(validPayload({ sections: [] }))).toThrow(
      ReportValidationError
    );
    const missing = validPayload();
    delete (missing as Record<string, unknown>).sections;
    expect(() => parseSoulmateReportV1(missing)).toThrow(ReportValidationError);
    expect(() =>
      parseSoulmateReportV1(validPayload({ sections: Array.from({ length: 25 }, () => ({
        index: "01.",
        title: "T",
        body: "B",
      })) }))
    ).toThrow(ReportValidationError);
  });

  it("rejects blank section/point fields and oversized point lists", () => {
    const blankBody = validPayload();
    (blankBody.sections[0] as { body: string }).body = "  ";
    expect(() => parseSoulmateReportV1(blankBody)).toThrow(ReportValidationError);

    const blankPointTitle = validPayload();
    ((blankPointTitle.sections[0].points as Array<{ title?: string }>)[0] as { title: string }).title =
      "  ";
    expect(() => parseSoulmateReportV1(blankPointTitle)).toThrow(ReportValidationError);

    expect(() =>
      parseSoulmateReportV1(
        validPayload({
          sections: [
            {
              index: "01.",
              title: "T",
              body: "B",
              points: Array.from({ length: 13 }, () => ({ body: "P" })),
            },
          ],
        })
      )
    ).toThrow(ReportValidationError);
  });

  it("rejects duplicate section indexes (renderer keys and numbering integrity)", () => {
    const payload = validPayload();
    (payload.sections[1] as { index: string }).index = "01.";
    expect(() => parseSoulmateReportV1(payload)).toThrow(/Duplicate section index/);
  });

  it("rejects an explicit non-v1 schemaVersion", () => {
    expect(() => parseSoulmateReportV1(validPayload({ schemaVersion: "v2" }))).toThrow(
      /Unsupported report schema version/
    );
  });
});

describe("parseSoulmateReportV1 — plain-text content policy (SP-703 acceptance #4)", () => {
  const malicious = [
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
  ];

  const targets: Array<[string, (payload: Record<string, unknown>, value: string) => void]> = [
    ["title", (p, v) => { p.title = v; }],
    ["intro", (p, v) => { p.intro = v; }],
    ["closing", (p, v) => { p.closing = v; }],
    ["section title", (p, v) => { (p.sections as Array<Record<string, unknown>>)[0].title = v; }],
    ["section body", (p, v) => { (p.sections as Array<Record<string, unknown>>)[0].body = v; }],
    ["point title", (p, v) => {
      ((p.sections as Array<Record<string, unknown>>)[0].points as Array<Record<string, unknown>>)[0].title = v;
    }],
    ["point body", (p, v) => {
      ((p.sections as Array<Record<string, unknown>>)[0].points as Array<Record<string, unknown>>)[0].body = v;
    }],
  ];

  it.each(targets.map(([label]) => label))("rejects executable content in %s", (label) => {
    const target = targets.find(([l]) => l === label)!;
    for (const value of malicious) {
      const payload = validPayload();
      target[1](payload, value);
      expect(() => parseSoulmateReportV1(payload)).toThrow(ReportValidationError);
    }
  });
});

describe("isSoulmateReportV1", () => {
  it("returns true for valid payloads and false for violations without throwing", () => {
    expect(isSoulmateReportV1(validPayload())).toBe(true);
    expect(isSoulmateReportV1(validPayload({ title: "<script>x</script>" }))).toBe(false);
    expect(isSoulmateReportV1(null)).toBe(false);
  });
});

describe("M5 remediation: cross-stack closing parity (M-02)", () => {
  // The exact serialization the BACKEND parser produces for a payload with a blank
  // optional closing (model_dump(by_alias=True, exclude_none=True) — generated via
  // app.soulmate.domain.report.parse_soulmate_report_v1). It must pass the frontend
  // gate unchanged, with closing normalized to absent.
  const BACKEND_SERIALIZED_BLANK_CLOSING = {
    schemaVersion: "v1",
    title: "Backend Serialized Report",
    intro: "Produced by the backend parser with a blank optional closing.",
    sections: [
      {
        index: "01.",
        title: "Section One",
        body: "Plain body.",
        points: [{ title: "Point", body: "Point body." }],
      },
    ],
  };

  it("accepts the backend-serialized payload (closing already normalized away)", () => {
    const parsed = parseSoulmateReportV1(BACKEND_SERIALIZED_BLANK_CLOSING);
    expect(parsed.closing).toBeUndefined();
    expect(parsed.title).toBe("Backend Serialized Report");
  });

  it("normalizes a raw blank closing to absent instead of rejecting (backend parity)", () => {
    for (const blank of ["", "   ", " \n\t "]) {
      const parsed = parseSoulmateReportV1(validPayload({ closing: blank }));
      expect(parsed.closing).toBeUndefined();
    }
  });

  it("still rejects markup-bearing closing content", () => {
    expect(() => parseSoulmateReportV1(validPayload({ closing: "<b>x</b>" }))).toThrow(
      ReportValidationError
    );
  });
});
