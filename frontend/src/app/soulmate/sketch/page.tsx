"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SketchViewer, SketchViewState } from "@/soulmate/components/sketch";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";

function SketchPageContent() {
  const searchParams = useSearchParams();

  // DEV-SPEC §3: Production access requires entitlement confirmation.
  // In development or when fixture=true, default to "completed" fixture; otherwise default to "loading".
  const isFixture =
    searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production";
  const defaultState: SketchViewState = isFixture ? "completed" : "loading";

  const stateParam = (searchParams.get("state") || defaultState) as SketchViewState;
  const validState: SketchViewState = ["loading", "completed", "failed"].includes(stateParam)
    ? stateParam
    : defaultState;

  const gender = searchParams.get("gender") || "female";
  const defaultUrl =
    gender.toLowerCase() === "male"
      ? "/images/email/sketch-male.png"
      : "/images/email/sketch-female.png";

  const durableUrl = searchParams.get("url") || defaultUrl;
  const backUrl = sanitizeInternalRoute(searchParams.get("backUrl"));
  const showToolbar = isFixture;

  return (
    <SketchViewer
      state={validState}
      durableUrl={durableUrl}
      backUrl={backUrl}
      showFixtureToolbar={showToolbar}
    />
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
