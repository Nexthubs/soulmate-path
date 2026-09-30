"use client";

import React from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { SOULMATE_ROUTES } from "@/soulmate/domain";
import { DrawerMenuButton } from "@/soulmate/components/drawer";
import { trackSoulmateEvent } from "@/soulmate/analytics";

export interface SoulmateLandingPageProps {
  /**
   * Optional custom handler when CTA button is clicked.
   * If not provided, initiates fixture session and navigates to Transition-0.
   */
  onStartSession?: () => void;

  /**
   * Destination route when CTA is clicked. Defaults to Transition-0 (/soulmate/loading?step=0).
   */
  nextRoute?: string;

  /**
   * Target URL for Login button. Defaults to /login.
   */
  loginUrl?: string;

  /**
   * Marketing and compliance gate (DEV-SPEC §21 & LEGAL-01).
   * Unverified marketing badges (3M+ sketches, 18K+ 5 star reviews) and media logos
   * must not be displayed in production without verification.
   * Defaults to true in non-production environments or if NEXT_PUBLIC_ENABLE_MARKETING_CLAIMS === "true".
   */
  showMarketingClaims?: boolean;
}

export function SoulmateLandingPage({
  onStartSession,
  nextRoute = `${SOULMATE_ROUTES.LOADING}?step=0`,
  loginUrl = "/login",
  showMarketingClaims,
}: SoulmateLandingPageProps) {
  const router = useRouter();

  // §18.1 landing view: attribution comes from URL query only (no PII).
  const landingTrackedRef = React.useRef(false);
  React.useEffect(() => {
    if (landingTrackedRef.current) return;
    landingTrackedRef.current = true;
    let source: string | undefined;
    let campaign: string | undefined;
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      source = params.get("utm_source") || undefined;
      campaign = params.get("utm_campaign") || undefined;
    }
    trackSoulmateEvent({ name: "soulmate_landing_view", properties: { source, campaign } });
  }, []);

  const handleLoginClick = () => {
    trackSoulmateEvent({ name: "soulmate_login_click", properties: {} });
  };

  // Determine whether to display marketing badges per LEGAL-01 compliance gate
  // In production, unverified marketing claims are strictly disabled regardless of query or props.
  const isProduction = process.env.NODE_ENV === "production";
  const shouldShowClaims =
    !isProduction &&
    (showMarketingClaims ??
      (process.env.NEXT_PUBLIC_ENABLE_MARKETING_CLAIMS === "true"));

  const handleStart = () => {
    trackSoulmateEvent({ name: "soulmate_start_click", properties: {} });
    if (onStartSession) {
      onStartSession();
      return;
    }

    // Initialize fixture session in client storage if not already present
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem("soulmate_session_id", "fixture-session-101");
        sessionStorage.setItem("soulmate_current_step", "transition-0");
      } catch {
        // Storage might be restricted in some iframe or privacy environments
      }
    }

    router.push(nextRoute);
  };

  return (
    // Full-width warm background layer (batch 1 follow-up); the centered
    // max-390px slot keeps the 390px geometry while the gradient covers the
    // whole viewport on wide screens — same split as QuizShell/TransitionShell.
    <div className="flex flex-col w-full sp-fill-vh bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900 overflow-x-hidden">
      <div className="flex flex-col flex-1 justify-between items-center w-full max-w-[390px] mx-auto selection:bg-purple-200">
      {/* Header — TopAppBar (Figma Node 102:46) */}
      <header className="flex items-center justify-between px-6 pt-[calc(1.5rem+var(--sp-safe-top))] pb-2 w-full">
        <h1 className="font-serif text-[28px] leading-[26px] tracking-[0.425px] text-[#000000] select-none">
          Hint Soulmate
        </h1>
        <div className="flex items-center gap-2">
          <a
            href={loginUrl}
            onClick={handleLoginClick}
            className="font-sans text-[18px] leading-[24px] text-[#000000] hover:text-neutral-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded px-1.5 py-0.5"
            aria-label="Log in to existing account"
          >
            Login
          </a>
          {/* Shared trigger for the global AccountDrawer (SP-801; Figma 102:14) */}
          <DrawerMenuButton />
        </div>
      </header>

      {/* Main Hero Section (Figma Node 102:51) */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-2 text-center w-full">
        {/* Stats Badges — Guarded by LEGAL-01 Compliance Gate (Figma Node 102:53) */}
        {shouldShowClaims && (
          <div
            className="flex items-center justify-center gap-2.5 w-full mt-2 mb-4"
            data-testid="marketing-badges"
          >
            <div className="inline-flex items-center gap-1 px-4 py-1.5 rounded-full bg-[#8c52ff]/10 text-xs text-[#1b1b1b]">
              <span className="font-bold text-[12px]">3M+</span>
              <span className="font-normal text-[12px] text-neutral-700">sketches created</span>
            </div>
            <div className="inline-flex items-center gap-1 px-4 py-1.5 rounded-full bg-[#8c52ff]/10 text-xs text-[#1b1b1b]">
              <span className="font-bold text-[12px]">18K+</span>
              <span className="font-normal text-[12px] text-neutral-700">5 star reviews</span>
            </div>
          </div>
        )}

        {/* Main Headline (Figma Node 102:64) */}
        <h2 className="font-sans font-semibold text-[28px] leading-[36px] tracking-[0.5px] text-[#1b1b1b] max-w-[342px] mt-1 mb-6">
          <span className="text-[#6b38c2]">See the Face</span> of Your
          <br />
          Soulmate
        </h2>

        {/* Central Visual Concept (Figma Node 102:80) */}
        <div className="relative w-[256px] h-[256px] my-1 flex items-center justify-center">
          <Image
            src="/images/landing/soulmate-hero-illustration.png"
            alt="Soulmate silhouette preview with compatibility aspect badges"
            width={256}
            height={256}
            priority
            className="w-[256px] h-[256px] object-contain select-none pointer-events-none drop-shadow-sm"
          />
        </div>

        {/* Primary CTA (Figma Node 102:66) */}
        <div className="w-full max-w-[342px] mt-8 mb-2">
          <button
            type="button"
            onClick={handleStart}
            className="w-full h-[56px] bg-[#000000] hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-medium text-[18px] leading-[24px] rounded-lg shadow-md hover:shadow-lg transition-all flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer"
            aria-label="Let's begin finding your soulmate"
          >
            Let&apos;s begin
          </button>
        </div>

        {/* Featured In Media Logos (Figma Node 102:69) */}
        {shouldShowClaims && (
          <div
            className="w-full max-w-[342px] flex items-center justify-center my-3 opacity-90"
            data-testid="featured-in-media"
          >
            <Image
              src="/images/landing/featured-in.png"
              alt="Featured in Vice, Hello!, and Newsweek"
              width={342}
              height={36}
              className="h-8 object-contain"
            />
          </div>
        )}
      </main>

      {/* Footer (Figma Node 102:115) */}
      <footer className="w-full max-w-[342px] mx-auto px-4 pt-2 pb-6 text-center space-y-2.5">
        <p className="text-[11px] leading-[17.88px] text-[#6b7280]">
          By continuing, you agree to our{" "}
          <a
            href="#terms"
            className="underline hover:text-neutral-800 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-purple-500 rounded"
          >
            Terms &amp; Conditions
          </a>{" "}
          and{" "}
          <a
            href="#privacy"
            className="underline hover:text-neutral-800 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-purple-500 rounded"
          >
            Privacy Notice
          </a>
          . Have a question? Reach our support team{" "}
          <a
            href="mailto:support@soulmatepath.com"
            className="underline hover:text-neutral-800 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-purple-500 rounded"
          >
            here
          </a>
          .
        </p>

        <p className="text-[11px] leading-[16.5px] text-[#6b7280]">
          For entertainment purposes only
        </p>
      </footer>
      </div>
    </div>
  );
}
