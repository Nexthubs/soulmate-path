import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ReportRenderer,
  DEFAULT_REPORT_FIXTURE,
  SoulmateReportV1,
} from "../src/soulmate/components/report";
import { SOULMATE_ROUTES } from "../src/soulmate/domain";

// Mock next/navigation
const mockPush = vi.fn();
const mockBack = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: mockBack,
  }),
  useSearchParams: () => ({
    get: (key: string) => (key === "fixture" ? "true" : null),
  }),
}));

describe("SP-108: Report Renderer Fixture UI (DEV-SPEC §2, §13, §16; DECISIONS REPORT-01, REPORT-02, DOMAIN-01)", () => {
  describe("Structured Content Schema & Rendering (Acceptance #1)", () => {
    it("renders title, intro, and all sections from DEFAULT_REPORT_FIXTURE", () => {
      const html = renderToStaticMarkup(<ReportRenderer />);

      expect(html).toContain("data-testid=\"soulmate-report-renderer\"");
      expect(html).toContain("data-testid=\"report-title\"");
      expect(html).toContain("Your Soulmate Report");

      expect(html).toContain("data-testid=\"report-intro\"");
      expect(html).toContain("Before two souls cross paths in the physical realm");

      // Verify numbered sections
      expect(html).toContain("data-testid=\"report-section-01\"");
      expect(html).toContain("Releasing the Fear of Being Alone");
      expect(html).toContain("Desperation carries an emotional resonance of scarcity");

      expect(html).toContain("data-testid=\"report-section-02\"");
      expect(html).toContain("Tuning Your Energetic Signature");

      expect(html).toContain("data-testid=\"report-section-03\"");
      expect(html).toContain("Surrendering to Divine Timing");
    });

    it("renders optional points list with titles and bodies when provided", () => {
      const html = renderToStaticMarkup(<ReportRenderer />);

      expect(html).toContain("data-testid=\"section-points-list\"");
      expect(html).toContain("Morning Heart Opening");
      expect(html).toContain("3 minutes of slow somatic breathing");
      expect(html).toContain("Decluttering Stagnant Ties");
      expect(html).toContain("Mentally dissolving cords tied to past lovers");
      expect(html).toContain("Living in the Feeling State");
      expect(html).toContain("Feeling the tenderness and security now");
    });

    it("renders optional closing text when provided in schema", () => {
      const customReport: SoulmateReportV1 = {
        title: "Test Report",
        intro: "Intro text",
        sections: [
          {
            index: "01.",
            title: "First Step",
            body: "Body text",
          },
        ],
        closing: "May love find you in serene perfection.",
      };

      const html = renderToStaticMarkup(
        <ReportRenderer report={customReport} />
      );

      expect(html).toContain("data-testid=\"report-closing\"");
      expect(html).toContain("May love find you in serene perfection.");
    });
  });

  describe("Long Content Safe Wrapping (Acceptance #2)", () => {
    it("applies break-words and whitespace-pre-line to prevent viewport overflow", () => {
      const longUnbrokenWord = "SupercalifragilisticexpialidociousEnergeticSoulmateVibrationalResonanceAlignment";
      const customReport: SoulmateReportV1 = {
        title: longUnbrokenWord,
        intro: `First line of intro\nSecond line after newline with ${longUnbrokenWord}`,
        sections: [
          {
            index: "01.",
            title: `Title with ${longUnbrokenWord}`,
            body: `Long paragraph line 1\nLong paragraph line 2 with ${longUnbrokenWord}`,
            points: [
              {
                title: `Point ${longUnbrokenWord}`,
                body: `Point body with ${longUnbrokenWord}`,
              },
            ],
          },
        ],
      };

      const html = renderToStaticMarkup(
        <ReportRenderer report={customReport} />
      );

      // Verify safe wrap classes
      expect(html).toContain("break-words");
      expect(html).toContain("whitespace-pre-line");
      expect(html).toContain("overflow-x-hidden");
      expect(html).toContain(longUnbrokenWord);
    });
  });

  describe("Figma Editorial Visual Fidelity (Figma 102:1358 / Acceptance #3)", () => {
    it("renders amber index prefixes, amber bullet dots, and celestial end mark", () => {
      const html = renderToStaticMarkup(<ReportRenderer />);

      // Amber index prefix: text-[#b45309]
      expect(html).toContain("text-[#b45309]");
      expect(html).toContain("01.");
      expect(html).toContain("02.");
      expect(html).toContain("03.");

      // Amber bullet dot: bg-[#f59e0b]
      expect(html).toContain("bg-[#f59e0b]");

      // Celestial end mark: ✦ ✦ ✦
      expect(html).toContain("data-testid=\"report-celestial-end-mark\"");
      expect(html).toContain("✦ ✦ ✦");
    });

    it("conforms to 390px mobile baseline container", () => {
      const html = renderToStaticMarkup(<ReportRenderer />);
      expect(html).toContain("max-w-[390px]");
    });
  });

  describe("Zero Production AI Dependency (Acceptance #4 & REPORT-01/02)", () => {
    it("renders pure structured JSON data without invoking external AI services", () => {
      const customPureJson: SoulmateReportV1 = {
        title: "Deterministic Report V1",
        intro: "Purely structured content without runtime AI prompt synthesis.",
        sections: [
          {
            index: "01.",
            title: "Deterministic Section",
            body: "Verified deterministic output.",
          },
        ],
      };

      const html = renderToStaticMarkup(
        <ReportRenderer report={customPureJson} />
      );

      expect(html).toContain("Deterministic Report V1");
      expect(html).toContain("Purely structured content without runtime AI prompt synthesis.");
      expect(html).toContain("Deterministic Section");
      expect(html).toContain("Verified deterministic output.");
    });
  });

  describe("Routing Safety & Domain Invariants (DOMAIN-01)", () => {
    it("uses SOULMATE_ROUTES.RESULT as default back target without hardcoded domain strings", () => {
      expect(SOULMATE_ROUTES.RESULT).toBe("/soulmate/result");
      expect(SOULMATE_ROUTES.RESULT).not.toContain("https://");
      expect(SOULMATE_ROUTES.RESULT).not.toContain("stella.love");

      const html = renderToStaticMarkup(<ReportRenderer />);
      expect(html).toContain("data-testid=\"report-back-button\"");
      expect(html).toContain("aria-label=\"Go back to previous page\"");
    });
  });

  describe("Fixture Toolbar Controls", () => {
    it("renders fixture toolbar when showFixtureToolbar is true", () => {
      const html = renderToStaticMarkup(
        <ReportRenderer showFixtureToolbar={true} />
      );

      expect(html).toContain("data-testid=\"report-fixture-toolbar\"");
      expect(html).toContain("data-testid=\"fixture-btn-canonical\"");
      expect(html).toContain("data-testid=\"fixture-btn-minimal\"");
      expect(html).toContain("data-testid=\"fixture-btn-long\"");
    });

    it("omits fixture toolbar when showFixtureToolbar is false", () => {
      const html = renderToStaticMarkup(
        <ReportRenderer showFixtureToolbar={false} />
      );

      expect(html).not.toContain("data-testid=\"report-fixture-toolbar\"");
    });
  });
});
