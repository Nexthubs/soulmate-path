"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SketchViewer, SketchViewState } from "@/soulmate/components/sketch";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function SketchPageContent() {
  const searchParams = useSearchParams();

  const stateParam = (searchParams.get("state") || "completed") as SketchViewState;
  const validState: SketchViewState = ["loading", "completed", "failed"].includes(stateParam)
    ? stateParam
    : "completed";

  const gender = searchParams.get("gender") || "female";
  const defaultUrl =
    gender.toLowerCase() === "male"
      ? "/images/email/sketch-male.png"
      : "/images/email/sketch-female.png";

  const durableUrl = searchParams.get("url") || defaultUrl;
  const backUrl = searchParams.get("backUrl") || SOULMATE_ROUTES.RESULT;
  const showToolbar =
    searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production";

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
