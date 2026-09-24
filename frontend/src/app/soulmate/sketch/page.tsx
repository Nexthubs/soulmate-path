"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SketchViewer, SketchViewState } from "@/soulmate/components/sketch";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { sanitizeInternalRoute } from "@/soulmate/domain";

function SketchPageContent() {
  const searchParams = useSearchParams();

  // DEV-SPEC §3, AGENTS.md §5: Production access requires entitlement confirmation.
  // In production, client URL parameters (?state=completed&url=...) must NOT bypass entitlement.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture =
    !isProduction &&
    (searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production");
  const guardEnabled = isProduction || (!isFixture && searchParams.get("guard") === "true");

  // DEV-SPEC §3: Route Guard for /soulmate/sketch (First payment confirmed + 12h unlocked)
  const guard = useRouteGuard({
    targetRoute: "/soulmate/sketch",
    enabled: guardEnabled,
  });

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
          <h2 className="text-xl font-bold text-neutral-900">Sketch Locked</h2>
          <p className="text-sm text-neutral-600 leading-relaxed">
            {guard.error
              ? `Verification failed: ${guard.error}. Please retry.`
              : guard.verdict?.reason || "Active payment is required to unlock your soulmate sketch (DEV-SPEC §3)."}
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
