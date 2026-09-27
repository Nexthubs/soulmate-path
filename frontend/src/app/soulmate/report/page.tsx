"use client";

import React, { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ReportRenderer } from "@/soulmate/components/report";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { deriveReportViewState, useReportStatus } from "@/soulmate/hooks/useReportStatus";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";

function SharedPageChrome({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
      <header className="w-full flex justify-between items-center py-4">
        <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
      </header>
      <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
        {children}
      </div>
      <footer className="py-4 text-xs text-neutral-400">
        Hint Soulmate &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}

function ReportPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // DEV-SPEC §3, AGENTS.md §5: Production access requires entitlement confirmation.
  // Fixture preview is an explicit dev-mode opt-in (?fixture=true); the default is LIVE.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture = !isProduction && searchParams.get("fixture") === "true";
  const guardEnabled = isProduction || (!isFixture && searchParams.get("guard") === "true");
  const isLive = !isFixture;

  // DEV-SPEC §3: Route Guard for /soulmate/report (First payment confirmed + 24h unlocked).
  // Locked users route to Result (server verdict redirect_to, TIME-01).
  const guard = useRouteGuard({
    targetRoute: "/soulmate/report",
    enabled: guardEnabled,
  });

  // Live mode (M5 review H-01): authoritative session-scoped report state and
  // validated content from GET /api/soulmate/artifacts/report (SP-702). The stored,
  // server-validated ReportV1 is the only thing ever rendered — no generation exists
  // client-side (REPORT-01/02 keep production generation off; SP-706 owns the trigger).
  const report = useReportStatus({
    enabled: isLive && guard.allowed !== false,
  });

  const viewState = isFixture
    ? "completed"
    : deriveReportViewState(report.data?.report?.status);

  // ASSET-01-style defense-in-depth (mirrors the sketch page): a COMPLETED status
  // without validated content degrades to the support state — the page NEVER
  // substitutes the Figma fixture for the user's stored report.
  const liveContent = report.data?.content ?? null;
  const effectiveViewState =
    !isFixture && viewState === "completed" && !liveContent ? "failed" : viewState;

  // §10.3: LOCKED users route to the Result page (countdown lives there, TIME-01).
  useEffect(() => {
    if (!isLive) return;
    if (guard.allowed === false && !guard.error && guard.verdict?.redirect_to) {
      router.replace(guard.verdict.redirect_to);
    }
  }, [isLive, guard.allowed, guard.error, guard.verdict?.redirect_to, router]);

  useEffect(() => {
    if (!isLive) return;
    if (viewState === "locked") {
      router.replace(SOULMATE_ROUTES.RESULT);
    }
  }, [isLive, viewState, router]);

  const backUrl = sanitizeInternalRoute(searchParams.get("backUrl"), SOULMATE_ROUTES.RESULT);

  if (guard.allowed === false && guardEnabled) {    return (
      <SharedPageChrome>
        <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto text-xl">
          🔒
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Soulmate Report Locked</h2>
        <p className="text-sm text-neutral-600 leading-relaxed">
          {guard.error
            ? `Verification failed: ${guard.error}. Please retry.`
            : guard.verdict?.reason || "Active payment is required to unlock your detailed report (DEV-SPEC §3)."}
        </p>
        {guard.error ? (
          <button
            onClick={guard.retry}
            className="w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
          >
            Retry Verification
          </button>
        ) : (
          <a
            href={guard.verdict?.redirect_to || SOULMATE_ROUTES.SUBSCRIBE}
            className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
          >
            Continue
          </a>
        )}
      </SharedPageChrome>
    );
  }

  // Live fetch error with no authoritative state: offer a retry of the READ only.
  if (isLive && report.error && !report.data) {
    return (
      <SharedPageChrome>
        <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mx-auto text-xl">
          ⏳
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Something Went Wrong</h2>
        <p className="text-sm text-neutral-600 leading-relaxed">
          {report.error}. Your report is safe — please try again.
        </p>
        <button
          onClick={() => void report.refresh()}
          data-testid="report-refresh-read"
          className="w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
        >
          Try Again
        </button>
      </SharedPageChrome>
    );
  }

  // Live non-completed states (READY / GENERATING / FAILED): status cards. LOCKED is
  // redirected to Result above; the server decides when generation may run, so these
  // states never offer a client-side generation action (REPORT-01/02, SP-706).
  if (
    isLive &&
    (effectiveViewState === "ready" ||
      effectiveViewState === "loading" ||
      effectiveViewState === "failed")
  ) {
    const copy =
      effectiveViewState === "ready"
        ? "Your detailed report is being prepared. Please check back shortly."
        : effectiveViewState === "loading"
          ? "Your detailed report is being written right now. This page will show it as soon as it is ready."
          : "Your report could not be generated automatically. Please contact support if this persists.";
    const icon = effectiveViewState === "failed" ? "⚠️" : "⏳";
    const iconBg =
      effectiveViewState === "failed" ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-600";
    return (
      <SharedPageChrome>
        <div
          data-testid={`report-${effectiveViewState}-state`}
          className={`w-12 h-12 rounded-full ${iconBg} flex items-center justify-center mx-auto text-xl`}
        >
          {icon}
        </div>
        <h2 className="text-xl font-bold text-neutral-900">
          {effectiveViewState === "failed" ? "Report Unavailable" : "Soulmate Report"}
        </h2>
        <p className="text-sm text-neutral-600 leading-relaxed">{copy}</p>
        <Link
          href={backUrl}
          className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
        >
          Return to Dashboard
        </Link>
      </SharedPageChrome>
    );
  }

  // Live loading/unknown: neutral loading card until the authoritative state arrives.
  if (isLive && effectiveViewState !== "completed") {
    return (
      <div className="flex items-center justify-center min-h-screen text-neutral-400">
        Loading report...
      </div>
    );
  }

  return (
    <>
      {isFixture && (
        <div
          data-testid="report-fixture-banner"
          className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
        >
          [Demo Preview (Unpublished Fixture Content)]
        </div>
      )}
      {/*
        COMPLETED (live or fixture): the renderer consumes ONLY validated ReportV1 —
        its SP-703 gate re-validates whatever this page passes, and live content was
        additionally validated server-side on read (SP-702). Live mode passes the
        stored content only (never the Figma fixture).
      */}
      <ReportRenderer
        report={isLive ? liveContent ?? undefined : undefined}
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
