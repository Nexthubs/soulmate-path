"use client";

import React, { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SketchViewer, SketchViewState } from "@/soulmate/components/sketch";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { useSketchStatus, deriveSketchViewState } from "@/soulmate/hooks/useSketchStatus";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";
import { trackArtifactUnlocked, trackSoulmateEvent } from "@/soulmate/analytics";

function SketchPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // DEV-SPEC §3, AGENTS.md §5: Production access requires entitlement confirmation.
  // In production, client URL parameters (?state=completed&url=...) must NOT bypass entitlement.
  // Fixture preview is an explicit dev-mode opt-in (?fixture=true); the default is LIVE.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture = !isProduction && searchParams.get("fixture") === "true";
  const guardEnabled = isProduction || (!isFixture && searchParams.get("guard") === "true");
  const isLive = !isFixture;

  // DEV-SPEC §3: Route Guard for /soulmate/sketch (First payment confirmed + 12h unlocked).
  // Locked users route to Result (server verdict redirect_to, TIME-01).
  const guard = useRouteGuard({
    targetRoute: "/soulmate/sketch",
    enabled: guardEnabled,
  });

  // Live mode: authoritative session-scoped sketch state (SP-607) with bounded
  // polling while GENERATING (SP-505 pattern). The server — never the client —
  // decides whether a generation may start, so refresh can never regenerate.
  const sketch = useSketchStatus({
    enabled: isLive && guard.allowed !== false,
    polling: isLive,
  });

  const viewState = isFixture
    ? ((searchParams.get("state") || "completed") as SketchViewState)
    : deriveSketchViewState(sketch.data?.sketch?.status);

  // The viewer renders four states; a LOCKED page is about to redirect to Result
  // (§10.3/TIME-01), and an unloaded page shows the neutral loading card.
  // ASSET-01 defense-in-depth: the live page never substitutes a sample image for
  // the user's portrait — a COMPLETED status without a display URL degrades to the
  // support state instead of rendering a placeholder portrait.
  const liveImageUrl = sketch.data?.image_url ?? undefined;
  const liveRetryable = sketch.data?.retry_available !== false;
  const effectiveViewState =
    !isFixture && viewState === "completed" && !liveImageUrl ? "failed" : viewState;
  const viewerState: SketchViewState =
    effectiveViewState === null || effectiveViewState === "locked" ? "loading" : effectiveViewState;

  // §10.3: LOCKED users route to the Result page (countdown lives there, TIME-01).
  useEffect(() => {
    if (!isLive) return;
    if (guard.allowed === false && !guard.error && guard.verdict?.redirect_to) {
      router.replace(guard.verdict.redirect_to);
      return;
    }
    if (viewState === "locked") {
      router.replace(SOULMATE_ROUTES.RESULT);
    }
  }, [isLive, guard.allowed, guard.error, guard.verdict?.redirect_to, viewState, router]);

  const gender = searchParams.get("gender") || "female";
  const defaultUrl =
    gender.toLowerCase() === "male"
      ? "/images/email/sketch-male.png"
      : "/images/email/sketch-female.png";

  const durableUrl = isFixture
    ? searchParams.get("url") || defaultUrl
    : liveImageUrl;
  const backUrl = sanitizeInternalRoute(searchParams.get("backUrl"));
  const showToolbar = isFixture;

  // §18.1: first live unlocked view of the sketch page also marks the unlock
  // (deduplicated with the Result dashboard by the analytics wrapper), and the
  // displayed durable asset marks `soulmate_sketch_viewed`.
  const sketchUnlockedTrackedRef = React.useRef(false);
  React.useEffect(() => {
    if (!isLive || guard.allowed === false) return;
    if (viewState === "locked" || viewState === null) return;
    if (sketchUnlockedTrackedRef.current) return;
    sketchUnlockedTrackedRef.current = true;
    // Identity is cookie-bound on this page (no public session id in scope).
    trackArtifactUnlocked("sketch", {});
  }, [isLive, guard.allowed, viewState]);

  const sketchViewedTrackedRef = React.useRef(false);
  React.useEffect(() => {
    if (!isLive || effectiveViewState !== "completed" || !liveImageUrl) return;
    if (sketchViewedTrackedRef.current) return;
    sketchViewedTrackedRef.current = true;
    trackSoulmateEvent({
      name: "soulmate_sketch_viewed",
      // The artifact version is not exposed by the artifact status API yet;
      // null documents the intent until the response carries it.
      properties: { artifact_version: null },
    });
  }, [isLive, effectiveViewState, liveImageUrl]);

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
              href={guard.verdict?.redirect_to || SOULMATE_ROUTES.SUBSCRIBE}
              className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors text-center"
            >
              Continue
            </a>
          )}
        </div>

        <footer className="py-4 text-xs text-neutral-400">
          Hint Soulmate &copy; {new Date().getFullYear()}
        </footer>
      </main>
    );
  }

  // Live fetch error with no authoritative state: offer a retry of the READ
  // (never a generation — the server decides when generation may start).
  if (isLive && sketch.error && !sketch.data) {
    return (
      <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
        <header className="w-full flex justify-between items-center py-4">
          <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
        </header>

        <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
          <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mx-auto text-xl">
            ⏳
          </div>
          <h2 className="text-xl font-bold text-neutral-900">Something Went Wrong</h2>
          <p className="text-sm text-neutral-600 leading-relaxed">
            {sketch.error}. Your sketch is safe — please try again.
          </p>
          <button
            onClick={() => void sketch.refresh()}
            data-testid="sketch-refresh-read"
            className="w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
          >
            Try Again
          </button>
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
        state={viewerState}
        durableUrl={durableUrl}
        backUrl={backUrl}
        showFixtureToolbar={showToolbar}
        isTriggering={sketch.isTriggering}
        retryAvailable={isFixture ? true : liveRetryable}
        onCheckNow={isLive ? () => void sketch.triggerGeneration() : undefined}
        onRetry={isLive ? () => void sketch.triggerGeneration() : undefined}
        errorMessage={
          isLive && effectiveViewState === "failed" && !liveRetryable
            ? "Your sketch could not be generated automatically."
            : undefined
        }
        partnerGender={gender === "male" ? "Prince Charming" : "Dream Girl"}
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
