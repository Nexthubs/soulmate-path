"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { SOULMATE_ROUTES } from "@/soulmate/domain";
import {
  ReportRendererProps,
  SoulmateReportV1,
  DEFAULT_REPORT_FIXTURE,
} from "./types";

/**
 * Editorial Report Renderer Component (Figma Node 102:1358; DEV-SPEC §2, §13, §16; DECISIONS REPORT-01, REPORT-02).
 * Renders structured SoulmateReportV1 JSON with safe wrapping and zero production AI dependencies.
 */
export function ReportRenderer({
  report: initialReport = DEFAULT_REPORT_FIXTURE,
  backUrl = SOULMATE_ROUTES.RESULT,
  onBack,
  showFixtureToolbar = false,
  className = "",
}: ReportRendererProps) {
  const router = useRouter();
  const [activeReport, setActiveReport] = useState<SoulmateReportV1>(initialReport);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      router.push(backUrl || SOULMATE_ROUTES.RESULT);
    }
  };

  return (
    <div
      data-testid="soulmate-report-renderer"
      className={`relative min-h-screen w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900 px-6 pt-7 pb-10 flex flex-col justify-between overflow-x-hidden ${className}`}
    >
      {/* Dev Fixture QA Toolbar */}
      {showFixtureToolbar && (
        <div
          data-testid="report-fixture-toolbar"
          className="w-full mb-4 p-2.5 bg-neutral-900/90 text-white rounded-xl text-xs space-y-1.5"
        >
          <div className="font-semibold text-neutral-300">Report Fixture Variant:</div>
          <div className="flex gap-1.5 flex-wrap">
            <button
              type="button"
              data-testid="fixture-btn-canonical"
              onClick={() => setActiveReport(DEFAULT_REPORT_FIXTURE)}
              className="px-2 py-1 rounded bg-amber-700 hover:bg-amber-600 text-[11px] font-medium cursor-pointer"
            >
              Canonical
            </button>
            <button
              type="button"
              data-testid="fixture-btn-minimal"
              onClick={() =>
                setActiveReport({
                  title: "Minimal Soulmate Reading",
                  intro: "A concise overview of soul connection.",
                  sections: [
                    {
                      index: "01.",
                      title: "Pure Connection",
                      body: "A single paragraph summary of the intuitive energetic match.",
                    },
                  ],
                })
              }
              className="px-2 py-1 rounded bg-neutral-700 hover:bg-neutral-600 text-[11px] font-medium cursor-pointer"
            >
              Minimal
            </button>
            <button
              type="button"
              data-testid="fixture-btn-long"
              onClick={() =>
                setActiveReport({
                  ...DEFAULT_REPORT_FIXTURE,
                  closing:
                    "May you walk forward in gentle clarity, trusting that the universe has already set your shared destiny into motion.",
                })
              }
              className="px-2 py-1 rounded bg-neutral-700 hover:bg-neutral-600 text-[11px] font-medium cursor-pointer"
            >
              With Closing
            </button>
          </div>
        </div>
      )}

      {/* Top Header & Back Navigation */}
      <header className="w-full flex items-center justify-between pb-5">
        <button
          type="button"
          onClick={handleBack}
          data-testid="report-back-button"
          aria-label="Go back to previous page"
          className="w-10 h-10 rounded-full bg-white/80 hover:bg-white shadow-xs border border-neutral-200/60 flex items-center justify-center text-neutral-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-600 cursor-pointer"
        >
          <svg className="w-5 h-5 fill-none stroke-current stroke-2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <span className="text-[11px] font-semibold tracking-wider uppercase text-amber-800/80 bg-amber-100/60 px-2.5 py-1 rounded-full">
          Intuitive Guide
        </span>
      </header>

      {/* Main Editorial Article Content */}
      <main className="w-full flex-1 space-y-6">
        {/* Editorial Headline (H1) - Figma 102:1363 */}
        <div className="space-y-3.5">
          <h1
            data-testid="report-title"
            className="font-sans font-bold text-[26px] leading-[33.5px] tracking-[-0.65px] text-[#2d2926] break-words"
          >
            {activeReport.title}
          </h1>

          {/* Lead Intro Paragraph - Figma 102:1365 */}
          <p
            data-testid="report-intro"
            className="font-sans font-normal text-[15px] leading-[24.75px] text-[#44403c] break-words whitespace-pre-line"
          >
            {activeReport.intro}
          </p>
        </div>

        {/* Numbered Sections List - Figma 102:1366, 102:1379, 102:1406 */}
        <div data-testid="report-sections-container" className="space-y-6 pt-1">
          {activeReport.sections.map((section, sIdx) => (
            <section
              key={section.index || sIdx}
              data-testid={`report-section-${section.index.replace(/[^a-zA-Z0-9]/g, "")}`}
              className="space-y-2.5"
            >
              {/* Heading 2 with Amber Index Prefix */}
              <div className="flex items-baseline gap-2">
                <span
                  data-testid="section-index"
                  className="font-sans font-medium text-[14px] leading-[20px] text-[#b45309] tracking-[-0.425px] shrink-0"
                >
                  {section.index}
                </span>
                <h2
                  data-testid="section-title"
                  className="font-sans font-semibold text-[17px] leading-[25.5px] text-[#2d2926] tracking-[-0.425px] break-words"
                >
                  {section.title}
                </h2>
              </div>

              {/* Section Body Text */}
              <p
                data-testid="section-body"
                className="font-sans font-light text-[13.5px] leading-[23.2px] text-[#57534e] break-words whitespace-pre-line"
              >
                {section.body}
              </p>

              {/* Optional Refined Step Points - Figma 102:1390 */}
              {section.points && section.points.length > 0 && (
                <ul
                  data-testid="section-points-list"
                  className="space-y-3 pt-2 pl-1"
                >
                  {section.points.map((point, pIdx) => (
                    <li
                      key={pIdx}
                      data-testid={`section-point-${pIdx}`}
                      className="flex items-start gap-2.5"
                    >
                      {/* Amber Bullet Dot - Figma 102:1393 */}
                      <span
                        aria-hidden="true"
                        className="w-1.5 h-1.5 rounded-full bg-[#f59e0b] mt-2 shrink-0"
                      />
                      <div className="font-sans text-[13px] leading-[18px] text-[#44403c] break-words">
                        {point.title && (
                          <strong className="font-semibold text-[#2d2926]">
                            {point.title}:{" "}
                          </strong>
                        )}
                        <span className="font-light text-[#57534e]">
                          {point.body}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>

        {/* Optional Closing Section (DEV-SPEC §13.2) */}
        {activeReport.closing && (
          <div
            data-testid="report-closing"
            className="pt-4 pb-2 text-center italic font-sans text-[14px] leading-[22px] text-[#78350f] break-words"
          >
            &ldquo;{activeReport.closing}&rdquo;
          </div>
        )}
      </main>

      {/* Celestial End Mark - Figma 102:1417 */}
      <footer
        data-testid="report-celestial-end-mark"
        className="w-full flex items-center justify-center gap-3 pt-8 pb-4"
      >
        <span className="w-12 h-[1px] bg-[#78350f]/15" aria-hidden="true" />
        <span
          data-testid="celestial-stars"
          className="font-serif text-[12px] tracking-[0.3em] text-[#b45309]/60 select-none"
        >
          ✦ ✦ ✦
        </span>
        <span className="w-12 h-[1px] bg-[#78350f]/15" aria-hidden="true" />
      </footer>
    </div>
  );
}
