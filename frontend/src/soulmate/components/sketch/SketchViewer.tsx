"use client";

import React, { useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";
import { SketchViewerProps, SketchViewState } from "./types";

/**
 * Sketch Viewer Component (Figma Node 102:461; DEV-SPEC §2, §10.3, §11; DECISIONS ASSET-01, DOMAIN-01).
 * Supports:
 * - ready state (UNLOCKED + NOT_STARTED, §10.3): "Generate My Sketch" CTA;
 * - loading state with animated progress and aria-busy;
 * - completed state displaying portrait from durable URL prop;
 * - failed state with error message and retry CTA;
 * - configurable back destination using route config without hardcoded domain strings.
 * The `state` prop drives the display whenever it changes (live mode); the fixture
 * toolbar still allows manual switching for QA previews.
 */
export function SketchViewer({
  state: initialState = "completed",
  durableUrl = "/images/email/sketch-female.png",
  title = "Your Personal Soulmate Insights",
  backUrl = SOULMATE_ROUTES.RESULT,
  onBack,
  onRetry,
  onCheckNow,
  isTriggering = false,
  retryAvailable = true,
  showFixtureToolbar = false,
  partnerGender,
  errorMessage,
  className = "",
}: SketchViewerProps) {
  const router = useRouter();
  const [currentState, setCurrentState] = useState<SketchViewState>(initialState);

  // Live mode: the authoritative server state (prop) always wins when it changes.
  useEffect(() => {
    setCurrentState(initialState);
  }, [initialState]);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      router.push(sanitizeInternalRoute(backUrl));
    }
  };

  const handleRetry = () => {
    if (onRetry) {
      onRetry();
    } else {
      // Transition to loading fixture
      setCurrentState("loading");
      setTimeout(() => setCurrentState("completed"), 1500);
    }
  };

  const handleCheckNow = () => {
    if (onCheckNow) {
      onCheckNow();
    } else {
      // Fixture default: pretend to generate.
      setCurrentState("loading");
      setTimeout(() => setCurrentState("completed"), 1500);
    }
  };

  return (
    <div
      data-testid="sketch-viewer"
      data-state={currentState}
      className={`relative min-h-screen w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900 px-5 py-6 flex flex-col justify-between overflow-x-hidden ${className}`}
    >
      {/* Dev Fixture Toolbar */}
      {showFixtureToolbar && (
        <div
          data-testid="sketch-fixture-toolbar"
          className="w-full mb-3 p-2 bg-neutral-900/90 text-white rounded-xl text-xs space-y-1"
        >
          <div className="font-semibold text-neutral-300">State Fixture:</div>
          <div className="flex gap-1">
            {(["ready", "loading", "completed", "failed"] as SketchViewState[]).map((s) => (
              <button
                key={s}
                type="button"
                data-testid={`fixture-tab-${s}`}
                onClick={() => setCurrentState(s)}
                className={`px-2 py-1 rounded capitalize text-[11px] cursor-pointer ${
                  currentState === s ? "bg-purple-600 font-bold" : "bg-neutral-700 hover:bg-neutral-600"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Top Header & Back Navigation */}
      <header className="w-full flex items-center justify-between pt-2 pb-4">
        <button
          type="button"
          onClick={handleBack}
          data-testid="sketch-back-button"
          aria-label="Go back to previous page"
          className="w-10 h-10 rounded-full bg-white/80 hover:bg-white shadow-xs border border-neutral-200/60 flex items-center justify-center text-neutral-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 cursor-pointer"
        >
          <svg className="w-5 h-5 fill-none stroke-current stroke-2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        {partnerGender && (
          <span className="text-xs font-semibold px-3 py-1 rounded-full bg-purple-100/70 text-purple-800">
            {partnerGender}
          </span>
        )}
      </header>

      {/* Heading Title (Figma 102:462) */}
      <div className="w-full text-center my-2">
        <h1 className="font-sans font-bold text-[24px] leading-[32px] tracking-tight text-neutral-900 max-w-[320px] mx-auto">
          {title}
        </h1>
      </div>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col items-center justify-center my-auto w-full py-4">
        {/* 0. READY STATE (UNLOCKED + NOT_STARTED, §10.3) */}
        {currentState === "ready" && (
          <div
            data-testid="sketch-ready-state"
            className="w-full max-w-[310px] rounded-[28px] bg-white/80 p-8 shadow-xl border border-purple-100 flex flex-col items-center text-center space-y-6"
          >
            <div className="w-24 h-24 rounded-full bg-[#faf5ff] border-2 border-[#e9d5ff] flex items-center justify-center text-[#7c3aed]">
              <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.5"
                  d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                />
              </svg>
            </div>

            <div className="space-y-2">
              <h3 className="font-sans font-bold text-[18px] text-neutral-900">
                Your Sketch Is Ready to Create
              </h3>
              <p className="text-xs text-neutral-500 leading-relaxed max-w-[240px]">
                Stella&apos;s artist is standing by. Tap below and your soulmate
                pencil portrait will be hand-crafted just for you.
              </p>
            </div>

            <button
              type="button"
              onClick={handleCheckNow}
              disabled={isTriggering}
              data-testid="sketch-check-now-cta"
              className="w-full h-[48px] rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 disabled:opacity-60 text-white font-sans font-semibold text-[14px] shadow-md flex items-center justify-center gap-2 transition-colors cursor-pointer"
            >
              {isTriggering ? "Starting..." : "Generate My Sketch"}
            </button>
          </div>
        )}

        {/* 1. LOADING STATE */}
        {currentState === "loading" && (
          <div
            data-testid="sketch-loading-state"
            aria-busy="true"
            className="w-full max-w-[310px] rounded-[28px] bg-white/80 p-8 shadow-xl border border-purple-100 flex flex-col items-center text-center space-y-6 animate-pulse"
          >
            {/* Animated drawing placeholder */}
            <div className="w-24 h-24 rounded-full bg-[#faf5ff] border-2 border-[#e9d5ff] flex items-center justify-center text-[#7c3aed]">
              <svg className="w-12 h-12 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.5"
                  d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                />
              </svg>
            </div>

            <div className="space-y-2">
              <h3 className="font-sans font-bold text-[18px] text-neutral-900">
                Drawing Your Soulmate...
              </h3>
              <p className="text-xs text-neutral-500 leading-relaxed max-w-[240px]">
                Stella&apos;s artist is hand-crafting your intuitive soulmate pencil portrait. This takes under a minute.
              </p>
            </div>

            <div className="w-full bg-purple-50 rounded-full h-2 overflow-hidden">
              <div className="bg-gradient-to-r from-purple-500 to-indigo-600 h-full w-3/4 rounded-full animate-pulse" />
            </div>
          </div>
        )}

        {/* 2. COMPLETED STATE (Figma 102:461) */}
        {currentState === "completed" && (
          <div
            data-testid="sketch-completed-state"
            className="w-full flex flex-col items-center space-y-5"
          >
            {/* Central Portrait Card Frame */}
            <div className="w-full max-w-[310px] rounded-[28px] bg-white p-3 shadow-2xl border border-neutral-100/90 flex items-center justify-center overflow-hidden">
              <div className="relative w-full aspect-[3/4] rounded-[20px] overflow-hidden bg-neutral-50">
                <Image
                  src={durableUrl}
                  alt="Your personalized soulmate pencil sketch portrait"
                  fill
                  className="object-cover object-top filter contrast-[1.02]"
                  priority
                  unoptimized
                  data-testid="sketch-portrait-image"
                />
              </div>
            </div>

            {/* Bottom Auxiliary Actions */}
            <div className="w-full max-w-[310px] flex items-center gap-3 pt-2">
              <a
                href={durableUrl}
                download="soulmate-sketch.png"
                data-testid="download-sketch-btn"
                className="flex-1 h-[48px] rounded-xl bg-white hover:bg-neutral-50 border border-neutral-200 text-neutral-800 font-sans font-semibold text-[14px] shadow-xs flex items-center justify-center gap-1.5 transition-colors"
              >
                <svg className="w-4 h-4 fill-none stroke-current stroke-2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                <span>Save Image</span>
              </a>

              <button
                type="button"
                onClick={() => router.push(SOULMATE_ROUTES.REPORT)}
                data-testid="view-report-cta"
                className="flex-1 h-[48px] rounded-xl bg-black hover:bg-neutral-800 text-white font-sans font-semibold text-[14px] shadow-md flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <span>View Report</span>
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </div>
        )}

        {/* 3. FAILED STATE */}
        {currentState === "failed" && (
          <div
            data-testid="sketch-failed-state"
            role="alert"
            className="w-full max-w-[310px] rounded-[28px] bg-white p-7 shadow-xl border border-red-200 flex flex-col items-center text-center space-y-5"
          >
            <div className="w-14 h-14 rounded-full bg-red-50 border border-red-200 flex items-center justify-center text-red-600">
              <svg className="w-7 h-7 fill-current" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
            </div>

            <div className="space-y-1.5">
              <h3 className="font-sans font-bold text-[18px] text-neutral-900">
                Generation Interrupted
              </h3>
              <p className="text-xs text-red-600 leading-relaxed">
                {errorMessage || "We encountered an issue generating your soulmate portrait. Please try again."}
              </p>
            </div>

            <div className="w-full flex flex-col gap-2 pt-2">
              {retryAvailable && (
                <button
                  type="button"
                  onClick={handleRetry}
                  data-testid="sketch-retry-btn"
                  className="w-full h-[48px] rounded-xl bg-red-600 hover:bg-red-700 text-white font-sans font-semibold text-[15px] shadow-md transition-colors cursor-pointer"
                >
                  Retry Generation
                </button>
              )}
              {!retryAvailable && (
                <p
                  data-testid="sketch-support-note"
                  className="text-xs text-neutral-500 leading-relaxed"
                >
                  Automatic retries have been exhausted for now. Please contact
                  support to restore your sketch — you will not be charged again.
                </p>
              )}
              <button
                type="button"
                onClick={handleBack}
                className="w-full h-[44px] rounded-xl bg-neutral-100 hover:bg-neutral-200 text-neutral-700 font-sans font-medium text-[14px] transition-colors cursor-pointer"
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
