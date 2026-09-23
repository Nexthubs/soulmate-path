/**
 * Domain types and fixtures for Soulmate Report (DEV-SPEC §2, §13, §16; DECISIONS REPORT-01, REPORT-02).
 */

export interface SoulmateReportSectionPoint {
  title?: string;
  body: string;
}

export interface SoulmateReportSection {
  index: string;
  title: string;
  body: string;
  points?: SoulmateReportSectionPoint[];
}

export interface SoulmateReportV1 {
  title: string;
  intro: string;
  sections: SoulmateReportSection[];
  closing?: string;
}

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
