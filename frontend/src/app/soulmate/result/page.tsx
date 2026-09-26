"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SoulmateResultView } from "@/soulmate/components/result";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { useResultAggregate } from "@/soulmate/hooks/useResultAggregate";

function ResultContent() {
  const searchParams = useSearchParams();
  const [email, setEmail] = React.useState<string>(
    searchParams.get("email") || ""
  );

  const sessionId = searchParams.get("session_id") || undefined;
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture = searchParams.get("fixture") === "true";
  const guardEnabled = isProduction || (!isFixture && searchParams.get("guard") === "true");

  // DEV-SPEC §3: Route Guard for /soulmate/result (First payment confirmed per PAY-AUTH-01)
  const guard = useRouteGuard({
    targetRoute: "/soulmate/result",
    enabled: guardEnabled,
  });

  // SP-504: live aggregate (server_time + subscription + sketch/report statuses).
  // SP-505: bounded polling while an artifact is GENERATING; fixture mode bypasses both.
  const live = useResultAggregate({
    sessionId,
    enabled: !isFixture && (!guardEnabled || guard.allowed === true),
    polling: !isFixture,
  });

  React.useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = sessionStorage.getItem("soulmate_user_email");
      if (stored) {
        setEmail(stored);
      }
    }
  }, []);

  const showToolbar = !isProduction && (searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production");

  // In production or when guard is enabled, if access is blocked or loading, prevent unentitled rendering (PAY-AUTH-01)
  if (guard.loading && guardEnabled) {
    return (
      <div data-testid="result-guard-loading" className="flex flex-col items-center justify-center min-h-[60vh] text-center p-6 space-y-3">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600 mx-auto" />
        <p className="text-neutral-600 text-sm">Verifying payment authorization...</p>
      </div>
    );
  }

  if (guard.allowed === false && guardEnabled) {
    return (
      <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
        <header className="w-full flex justify-between items-center py-4">
          <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
        </header>

        <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
          <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto text-xl">
            🔒
          </div>
          <h2 className="text-xl font-bold text-neutral-900">Access Restricted</h2>
          <p className="text-sm text-neutral-600 leading-relaxed">
            {guard.error
              ? `Verification failed: ${guard.error}. Please check your connection and retry.`
              : guard.verdict?.reason || "Active payment is required to view your soulmate results (PAY-AUTH-01)."}
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
              href={guard.verdict?.redirect_to || "/soulmate/subscribe"}
              className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors text-center"
            >
              Go to Subscription Checkout
            </a>
          )}
        </div>

        <footer className="py-4 text-xs text-neutral-400">
          Hint Soulmate &copy; {new Date().getFullYear()}
        </footer>
      </main>
    );
  }

  // ------------------------------------------------------------------
  // Live aggregate states (SP-504). Production must never render fixture
  // placeholder data; dev/test keep the neutral preview shell while loading
  // so the page renders a stable, non-personal skeleton.
  // ------------------------------------------------------------------
  if (!isFixture && live.isLoading && isProduction) {
    return (
      <div data-testid="result-live-loading" className="flex flex-col items-center justify-center min-h-[60vh] text-center p-6 space-y-3">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600 mx-auto" />
        <p className="text-neutral-600 text-sm">Preparing your results...</p>
      </div>
    );
  }

  if (!isFixture && live.error) {
    const isForbidden = live.errorStatus === 403;
    return (
      <div data-testid="result-live-error" className="flex flex-col items-center justify-center min-h-[60vh] text-center p-6 space-y-4">
        <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto text-xl">
          {isForbidden ? "🔒" : "⚠"}
        </div>
        <h2 className="text-xl font-bold text-neutral-900">
          {isForbidden ? "Access Restricted" : "Something went wrong"}
        </h2>
        <p className="text-sm text-neutral-600 leading-relaxed max-w-[300px]">
          {isForbidden
            ? "An active payment is required to view your soulmate results (PAY-AUTH-01)."
            : live.error}
        </p>
        {isForbidden ? (
          <a
            href="/soulmate/subscribe"
            className="inline-block w-full max-w-[300px] py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors text-center"
          >
            Go to Subscription Checkout
          </a>
        ) : (
          <button
            onClick={() => void live.refresh()}
            className="w-full max-w-[300px] py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  const liveData = !isFixture && live.data ? live.data : undefined;

  return (
    <>
      {!isProduction && (
        <div
          data-testid="result-fixture-banner"
          className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
        >
          {liveData ? "[Live Server Data]" : "[Demo Preview (Fixture Data)]"}
        </div>
      )}
      <SoulmateResultView
        initialData={liveData}
        clockOffsetMs={liveData ? live.clockOffsetMs : undefined}
        userEmail={email || "user@example.com"}
        showFixtureToolbar={showToolbar}
        onCountdownZero={liveData ? () => live.onCountdownZero() : undefined}
      />
    </>
  );
}

export default function SoulmateResultPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen text-neutral-400">
          Loading results...
        </div>
      }
    >
      <ResultContent />
    </Suspense>
  );
}
