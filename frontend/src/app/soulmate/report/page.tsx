"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ReportRenderer } from "@/soulmate/components/report";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";

function ReportPageContent() {
  const searchParams = useSearchParams();

  const backUrl = sanitizeInternalRoute(searchParams.get("backUrl"), SOULMATE_ROUTES.RESULT);
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture =
    !isProduction &&
    (searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production");

  // DEV-SPEC §3: Route Guard for /soulmate/report (First payment confirmed + 24h unlocked)
  useRouteGuard({
    targetRoute: "/soulmate/report",
    enabled: isProduction || (!isFixture && searchParams.get("guard") === "true"),
  });

  // In production, unentitled visitors must not directly access the unpublished fixture report (AGENTS.md §5, REPORT-01/02)
  if (isProduction) {
    return (
      <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
        <header className="w-full flex justify-between items-center py-4">
          <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
        </header>

        <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
          <div className="w-12 h-12 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center mx-auto text-xl">
            🔒
          </div>
          <h2 className="text-xl font-bold text-neutral-900">Soulmate Report Locked</h2>
          <p className="text-sm text-neutral-600 leading-relaxed">
            Your detailed Connection Insights report requires an active subscription entitlement.
          </p>
          <Link
            href={backUrl}
            className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
          >
            Return to Dashboard
          </Link>
        </div>

        <footer className="py-4 text-xs text-neutral-400">
          Hint Soulmate &copy; {new Date().getFullYear()}
        </footer>
      </main>
    );
  }

  return (
    <>
      <div
        data-testid="report-fixture-banner"
        className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
      >
        [Demo Preview (Unpublished Fixture Content)]
      </div>
      <ReportRenderer
        backUrl={backUrl}
        showFixtureToolbar={isFixture}
      />
    </>
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
