"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SketchViewer, SketchViewState } from "@/soulmate/components/sketch";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";

function SketchPageContent() {
  const searchParams = useSearchParams();

  // DEV-SPEC §3, AGENTS.md §5: Production access requires entitlement confirmation.
  // In production, client URL parameters (?state=completed&url=...) must NOT bypass entitlement.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture =
    !isProduction &&
    (searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production");

  const defaultState: SketchViewState = isFixture ? "completed" : "loading";
  // In production, state cannot be spoofed via URL query param
  const stateParam = isFixture
    ? ((searchParams.get("state") || defaultState) as SketchViewState)
    : "loading";
  const validState: SketchViewState = ["loading", "completed", "failed"].includes(stateParam)
    ? stateParam
    : defaultState;

  const gender = searchParams.get("gender") || "female";
  const defaultUrl =
    gender.toLowerCase() === "male"
      ? "/images/email/sketch-male.png"
      : "/images/email/sketch-female.png";

  const durableUrl = isFixture ? (searchParams.get("url") || defaultUrl) : defaultUrl;
  const backUrl = sanitizeInternalRoute(searchParams.get("backUrl"));
  const showToolbar = isFixture;

  return (
    <>
      {isFixture && (
        <div
          data-testid="sketch-fixture-banner"
          className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
        >
          [Demo Preview (Unauthenticated Fixture Data)]
        </div>
      )}
      <SketchViewer
        state={validState}
        durableUrl={durableUrl}
        backUrl={backUrl}
        showFixtureToolbar={showToolbar}
      />
    </>
  );
}

export default function SoulmateSketchPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen text-neutral-400">
          Loading sketch...
        </div>
      }
    >
      <SketchPageContent />
    </Suspense>
  );
}
