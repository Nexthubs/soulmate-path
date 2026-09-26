"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ResultItemCard } from "./ResultItemCard";
import {
  ArtifactType,
  CombinedUIState,
  ResultAggregateData,
} from "./types";

export interface SoulmateResultViewProps {
  /**
   * Aggregate result data backing the view. REQUIRED (Wave 5 audit H4): live callers pass
   * the fetched aggregate; the QA fixture path passes DEFAULT_RESULT_FIXTURE explicitly.
   * Refetched/polled data flows into the render without extra syncing (audit H5).
   */
  initialData: ResultAggregateData;

  /**
   * Client-to-server clock offset in milliseconds (SP-504, TIME-01). Forwarded to the cards
   * for countdown calibration; undefined falls back to `initialData.server_time`.
   */
  clockOffsetMs?: number | null;

  /**
   * User email to display in top bar.
   */
  userEmail?: string;

  /**
   * Whether to enable developer fixture toggle toolbar. Defaults to false.
   */
  showFixtureToolbar?: boolean;

  /**
   * Action handler override.
   */
  onAction?: (type: ArtifactType) => void;

  /**
   * Fired when a calibrated countdown reaches zero while the server still reports LOCKED.
   * The parent must refetch the aggregate; the server decides the unlock (SP-504, TIME-01).
   */
  onCountdownZero?: (type: ArtifactType) => void;

  /**
   * Optional accelerated checkout offer price (e.g. from server offer config).
   * Per PAY-01, defaults to undefined (no hardcoded production price).
   */
  acceleratedPrice?: string;

  /**
   * Optional custom container class name.
   */
  className?: string;
}

// Default fixture matching DEV-SPEC §10.4 and Figma 102:1201
export const DEFAULT_RESULT_FIXTURE: ResultAggregateData = {
  server_time: new Date().toISOString(),
  subscription: {
    provider: "paypal",
    provider_status: "ACTIVE",
    first_payment_at: new Date().toISOString(),
    next_billing_at: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
  },
  sketch: {
    unlock_at: new Date(Date.now() + 11 * 3600 * 1000 + 58 * 60 * 1000 + 4 * 1000).toISOString(),
    availability: "LOCKED",
    generation: "NOT_STARTED",
  },
  report: {
    // TIME-01: Report unlock schedule is +24h from first payment (DEV-SPEC §10.2, DECISIONS.md)
    unlock_at: new Date(Date.now() + 23 * 3600 * 1000 + 58 * 60 * 1000 + 4 * 1000).toISOString(),
    availability: "LOCKED",
    generation: "NOT_STARTED",
  },
};

/**
 * Full Result Screen Container (Figma Nodes 102:1201 & 102:1332; DEV-SPEC §2, §10).
 *
 * `initialData` is REQUIRED so a parent can never accidentally render fixture placeholder
 * data (Wave 5 audit H4): live callers pass the fetched aggregate; the QA fixture path
 * passes DEFAULT_RESULT_FIXTURE explicitly. Live refetches (SP-505 polling / zero-refetch)
 * flow straight into the render because data is DERIVED from the prop — audit H5 — and only
 * explicit dev/QA interactions (toolbar, retry preview) create a local override.
 */
export function SoulmateResultView({
  initialData,
  clockOffsetMs,
  userEmail = "user@example.com",
  showFixtureToolbar = false,
  onAction,
  onCountdownZero,
  acceleratedPrice,
  className = "",
}: SoulmateResultViewProps) {
  const router = useRouter();
  // H5 (Wave 5 audit): derive instead of copying the prop into state, so refetched/polled
  // aggregate data always reaches the mounted cards without a prop->state sync effect.
  const [previewOverride, setPreviewOverride] = useState<ResultAggregateData | null>(null);
  const data = previewOverride ?? initialData;

  const handleAction = (type: ArtifactType) => {
    if (onAction) {
      onAction(type);
      return;
    }
    if (type === "sketch") {
      router.push("/soulmate/sketch");
    } else {
      router.push("/soulmate/report");
    }
  };

  const handleRetry = (type: ArtifactType) => {
    // Dev/QA preview only: server state is authoritative for real data.
    setPreviewOverride((prev) => ({
      ...(prev ?? initialData),
      [type]: {
        ...(prev ?? initialData)[type],
        generation: "PROCESSING",
        error_message: undefined,
      },
    }));
  };

  // Fixture toggle helper for testing all 5 states (dev/QA only)
  const setPresetState = (stateName: CombinedUIState) => {
    const base = previewOverride ?? initialData;
    switch (stateName) {
      case "countdown":
        setPreviewOverride({
          ...base,
          sketch: {
            ...base.sketch,
            availability: "LOCKED",
            generation: "NOT_STARTED",
            unlock_at: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
          },
          report: {
            ...base.report,
            availability: "LOCKED",
            generation: "NOT_STARTED",
            unlock_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
          },
        });
        return;
      case "ready":
        setPreviewOverride({
          ...base,
          sketch: {
            ...base.sketch,
            availability: "UNLOCKED",
            generation: "NOT_STARTED",
          },
          report: {
            ...base.report,
            availability: "UNLOCKED",
            generation: "NOT_STARTED",
          },
        });
        return;
      case "generating":
        setPreviewOverride({
          ...base,
          sketch: {
            ...base.sketch,
            availability: "UNLOCKED",
            generation: "PROCESSING",
          },
          report: {
            ...base.report,
            availability: "UNLOCKED",
            generation: "PROCESSING",
          },
        });
        return;
      case "completed":
        setPreviewOverride({
          ...base,
          sketch: {
            ...base.sketch,
            availability: "UNLOCKED",
            generation: "COMPLETED",
            artifact_url: "/images/email/sketch-female.png",
          },
          report: {
            ...base.report,
            availability: "UNLOCKED",
            generation: "COMPLETED",
          },
        });
        return;
      case "failed":
        setPreviewOverride({
          ...base,
          sketch: {
            ...base.sketch,
            availability: "UNLOCKED",
            generation: "FAILED",
            error_message: "Network timeout while generating sketch image.",
          },
          report: {
            ...base.report,
            availability: "UNLOCKED",
            generation: "FAILED",
            error_message: "Failed to compile astrological chart insights.",
          },
        });
        return;
    }
  };

  return (
    <div
      data-testid="soulmate-result-view"
      className={`min-h-screen w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fbfaff] via-[#fff5f6] to-[#fff7eb] text-neutral-900 px-4 py-8 flex flex-col items-center justify-between ${className}`}
    >
      {/* Dev / QA Fixture State Switcher Toolbar */}
      {showFixtureToolbar && (
        <div
          data-testid="fixture-toolbar"
          className="w-full mb-4 p-2 bg-neutral-900/90 text-white rounded-xl text-xs space-y-1"
        >
          <div className="font-semibold text-neutral-300">Fixture State Preview:</div>
          <div className="flex flex-wrap gap-1">
            {(["countdown", "ready", "generating", "completed", "failed"] as CombinedUIState[]).map(
              (s) => (
                <button
                  key={s}
                  type="button"
                  data-testid={`fixture-btn-${s}`}
                  onClick={() => setPresetState(s)}
                  className="px-2 py-1 rounded bg-neutral-700 hover:bg-neutral-600 capitalize cursor-pointer text-[11px]"
                >
                  {s}
                </button>
              )
            )}
          </div>
        </div>
      )}

      {/* Top Bar with Brand & User Email & Settings */}
      <header className="w-full flex items-center justify-between pb-6 px-2">
        <span className="font-serif italic font-bold text-[26px] tracking-tight text-[#2c1e4a]">
          Hint
        </span>
        <div className="flex items-center gap-3">
          <span
            data-testid="user-email-header"
            className="font-sans text-[13px] text-neutral-500 font-medium truncate max-w-[160px]"
          >
            {userEmail}
          </span>
          <a
            href="/soulmate/settings"
            data-testid="settings-nav-link"
            className="text-neutral-400 hover:text-neutral-700 transition-colors p-1 text-sm font-semibold"
            title="Subscription Settings"
            aria-label="Subscription Settings"
          >
            ⚙
          </a>
        </div>
      </header>

      {/* Heading Section (Figma 102:1216) */}
      <div className="w-full text-left px-2 mb-4 flex items-center gap-2">
        <span className="text-[#a855f7] text-lg" aria-hidden="true">
          ✦
        </span>
        <h1 className="font-sans font-extrabold text-[24px] leading-[32px] text-neutral-900 tracking-tight">
          Your Soulmate Sketch
        </h1>
      </div>

      {/* Main Elevated Container (Figma 102:1201) */}
      <main className="w-full rounded-[32px] bg-white/95 shadow-xl border border-neutral-100 p-5 space-y-6">
        {/* Sketch Status Card */}
        <ResultItemCard
          type="sketch"
          state={data.sketch}
          serverTime={data.server_time}
          clockOffsetMs={clockOffsetMs}
          onAction={handleAction}
          onRetry={handleRetry}
          onCountdownZero={onCountdownZero}
        />

        {/* Report Status Card (Figma 102:1332) */}
        <ResultItemCard
          type="report"
          state={data.report}
          serverTime={data.server_time}
          clockOffsetMs={clockOffsetMs}
          onAction={handleAction}
          onRetry={handleRetry}
          onCountdownZero={onCountdownZero}
        />

        {/* Accelerated Early-Access Teaser Banner (Figma 102:1201; PAY-01 Compliance Gate) */}
        <section
          data-testid="accelerated-teaser"
          className="w-full pt-4 border-t border-neutral-100 flex flex-col items-center text-center space-y-3"
        >
          <div className="space-y-1">
            <h4 className="font-sans font-bold text-[18px] text-neutral-900">Just 5 minutes</h4>
            <p className="font-sans font-bold text-[15px] leading-snug text-neutral-800">
              Get an early look at<br />
              your portrait &amp; report!
            </p>
          </div>

          {acceleratedPrice ? (
            <div data-testid="accelerated-pricing-line" className="text-xs font-semibold text-neutral-600">
              Proceed to Payment: <strong className="text-neutral-900 text-sm">{acceleratedPrice}</strong>
            </div>
          ) : (
            <div data-testid="accelerated-pricing-line" className="text-xs font-medium text-neutral-500">
              Accelerated Access Coming Soon
            </div>
          )}

          <button
            type="button"
            data-testid="accelerated-cta-button"
            onClick={() => {
              if (acceleratedPrice) {
                handleAction("sketch");
              }
            }}
            disabled={!acceleratedPrice}
            className={`w-full h-[52px] rounded-2xl font-sans font-bold text-[16px] transition-all flex items-center justify-center gap-2 ${
              acceleratedPrice
                ? "bg-gradient-to-r from-[#ff6b6b] to-[#ff5252] hover:from-[#ff5b5b] hover:to-[#ff4242] active:scale-[0.99] text-white shadow-lg shadow-rose-200 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                : "bg-neutral-100 text-neutral-400 border border-neutral-200 cursor-not-allowed shadow-none"
            }`}
          >
            <span>{acceleratedPrice ? "Accelerated" : "Accelerated (Coming Soon)"}</span>
            <span aria-hidden="true">✦</span>
          </button>
        </section>
      </main>
    </div>
  );
}
