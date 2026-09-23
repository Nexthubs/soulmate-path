"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ReportRenderer } from "@/soulmate/components/report";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function ReportPageContent() {
  const searchParams = useSearchParams();

  const backUrl = searchParams.get("backUrl") || SOULMATE_ROUTES.RESULT;
  const showToolbar =
    searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production";

  return (
    <ReportRenderer
      backUrl={backUrl}
      showFixtureToolbar={showToolbar}
    />
  );
}

export default function SoulmateReportPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen text-neutral-400">
          Loading report...
        </div>
      }
    >
      <ReportPageContent />
    </Suspense>
  );
}
