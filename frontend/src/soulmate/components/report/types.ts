/**
 * Report component view types and fixtures (DEV-SPEC §2, §13, §16; DECISIONS REPORT-01, REPORT-02).
 *
 * The canonical SoulmateReportV1 contract lives in the domain layer
 * (`@/soulmate/domain/report`, the TS mirror of backend SP-701) and is re-exported
 * here for component consumers. Runtime validation is provided by
 * `parseSoulmateReportV1` in the same domain module (SP-703).
 */

export type {
  SoulmateReportSection,
  SoulmateReportSectionPoint,
  SoulmateReportV1,
} from "@/soulmate/domain/report";
export {
  REPORT_SCHEMA_VERSION,
  ReportValidationError,
  isSoulmateReportV1,
  parseSoulmateReportV1,
} from "@/soulmate/domain/report";

import type {
  SoulmateReportSection,
  SoulmateReportV1,
} from "@/soulmate/domain/report";

export interface ReportRendererProps {
  /**
   * Structured report data conforming to SoulmateReportV1 (DEV-SPEC §13.2).
   */
  report?: SoulmateReportV1;

  /**
   * Configurable back navigation destination (defaults to SOULMATE_ROUTES.RESULT; DOMAIN-01).
   */
  backUrl?: string;

  /**
   * Custom back action callback.
   */
  onBack?: () => void;

  /**
   * Whether to display the fixture QA preview controls.
   */
  showFixtureToolbar?: boolean;

  /**
   * Additional container CSS classes.
   */
  className?: string;
}

/**
 * Canonical editorial report fixture from Figma node 102:1358.
 */
export const DEFAULT_REPORT_FIXTURE: SoulmateReportV1 = {
  schemaVersion: "v1",
  title: "Your Soulmate Report",
  intro:
    "Before two souls cross paths in the physical realm, they rendezvous energetically. When you elevate your inner vibration to match love, longing ceases and recognition begins.",
  sections: [
    {
      index: "01.",
      title: "Releasing the Fear of Being Alone",
      body:
        "Desperation carries an emotional resonance of scarcity. When you focus on what is missing, the universe mirrors back that very void. Real alignment begins the moment you cherish your solitude as sacred preparation rather than an empty interval.",
    },
    {
      index: "02.",
      title: "Tuning Your Energetic Signature",
      body:
        "Your subconscious belief system emits waves across your aura. To become receptive to divine partnership, start grounding these three daily rituals:",
      points: [
        {
          title: "Morning Heart Opening",
          body:
            "3 minutes of slow somatic breathing, visualising warmth expanding from your chest.",
        },
        {
          title: "Decluttering Stagnant Ties",
          body:
            "Mentally dissolving cords tied to past lovers or unfulfilled promises.",
        },
        {
          title: "Living in the Feeling State",
          body:
            "Feeling the tenderness and security now, before meeting them in form.",
        },
      ],
    },
    {
      index: "03.",
      title: "Surrendering to Divine Timing",
      body:
        "Trust is the final catalyst of manifestation. When you remove timeline pressures, you allow divine synchronicity to orchestrate the meeting in unexpected, effortless grace.",
    },
  ],
};
