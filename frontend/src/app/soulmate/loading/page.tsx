"use client";

import React, { useState, Suspense } from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import {
  TransitionShell,
  Transition5Progress,
  InterstitialModal,
  InterstitialType,
} from "@/soulmate/components/transition";
import {
  getTransition2Copy,
  getTransition3Copy,
  TRANSITION_4_STATIC_COPY,
} from "@/soulmate/components/transition/copy";

function LoadingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Step 0 through 5 from query param, defaulting to 0
  const stepParam = parseInt(searchParams.get("step") || "0", 10);
  const step = isNaN(stepParam) || stepParam < 0 || stepParam > 5 ? 0 : stepParam;

  // Marketing Claims Compliance Gate (DEV-SPEC §21, LEGAL-01)
  const shouldShowMarketingClaims =
    searchParams.get("claims") === "true" ||
    (process.env.NEXT_PUBLIC_ENABLE_MARKETING_CLAIMS === "true" &&
      process.env.NODE_ENV !== "production");

  // Dynamic copy injection parameters
  const qualityParam = searchParams.get("quality");
  const transition2Subtitle = getTransition2Copy(qualityParam);
  const customTitle4 = searchParams.get("title");
  const customSubtitle4 = searchParams.get("subtitle");

  // Transition-3 Zodiac & Decision Style (DEV-SPEC §5.5)
  const zodiacParam = searchParams.get("zodiac") || "Virgo Sun";
  const decisionParam = searchParams.get("decision") || "both";
  const transition3Data = getTransition3Copy({
    zodiacLabel: zodiacParam,
    decisionStyle: decisionParam,
  });

  // State for sequential Transition-5 popups
  const [activePopup, setActivePopup] = useState<InterstitialType | null>(null);

  const handleContinue = () => {
    switch (step) {
      case 0:
        // Transition-0 -> Q02..Q06
        router.push("/soulmate/quiz?code=q02");
        break;
      case 1:
        // Transition-1 -> Q07
        router.push("/soulmate/quiz?code=q07");
        break;
      case 2:
        // Transition-2 -> Q08
        router.push("/soulmate/quiz?code=q08");
        break;
      case 3:
        // Transition-3 -> Q11
        router.push("/soulmate/quiz?code=q11");
        break;
      case 4:
        // Transition-4 -> Q12
        router.push("/soulmate/quiz?code=q12");
        break;
      case 5:
        // Transition-5 triggers sequential popups: spiritual -> psychic_artistry -> warning -> email
        setActivePopup("spiritual");
        break;
      default:
        router.push("/soulmate");
    }
  };

  const handleModalAnswer = (_answer: boolean) => {
    if (activePopup === "spiritual") {
      setActivePopup("psychic_artistry");
    } else if (activePopup === "psychic_artistry") {
      setActivePopup("warning");
      setActivePopup(null);
      // All popups completed -> proceed to Email Capture, forwarding quiz parameters (M-1)
      const params = new URLSearchParams();
      ["preferred_partner_gender", "partner_gender", "user_gender", "age_range", "ethnicity"].forEach((key) => {
        const val = searchParams.get(key);
        if (val) params.set(key, val);
      });
      const query = params.toString();
      router.push(`/soulmate/email${query ? `?${query}` : ""}`);
    }
  };

  return (
    <>
      {/* Transition-0 (Figma 102:245; LEGAL-01 Compliance Gate) */}
      {step === 0 && (
        <TransitionShell
          step={0}
          title={
            shouldShowMarketingClaims ? (
              <span>
                <span className="text-[#6b38c2]">3 Million+ people</span> have seen their Soulmate with Stella
              </span>
            ) : (
              <span>
                <span className="text-[#6b38c2]">Astrological Guidance</span> to Meet Your Soulmate
              </span>
            )
          }
          onContinue={handleContinue}
        >
          {shouldShowMarketingClaims ? (
            <div className="space-y-4 my-2 text-left">
              <div className="p-5 rounded-2xl bg-white/80 shadow-xs border border-neutral-100 space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-semibold text-neutral-900">Vickibeasly</span>
                  <span className="text-amber-500">★★★★★</span>
                </div>
                <p className="text-xs font-semibold text-neutral-800">
                  &ldquo;I couldn&apos;t believe my eyes!&rdquo;
                </p>
                <p className="text-xs text-neutral-600 leading-relaxed">
                  My soulmate sketch tremendously resembles the man I met three months ago and almost instantly fell in love with!
                </p>
              </div>

              <div className="space-y-2.5 pt-2">
                <div className="flex items-center gap-3 text-xs text-neutral-700">
                  <span className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-xs">👥</span>
                  <span><strong>900+ users</strong> have seen their soulmate today.</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-neutral-700">
                  <span className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-xs">✨</span>
                  <span>Trusted by over <strong>3 million</strong> people.</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4 my-2 text-left">
              <div className="p-5 rounded-2xl bg-white/80 shadow-xs border border-neutral-100 space-y-2">
                <h3 className="text-xs font-semibold text-neutral-900">
                  Intuitive Astrological Matching
                </h3>
                <p className="text-xs text-neutral-600 leading-relaxed">
                  Stella combines personalized astrology, intuitive portrait artistry, and behavioral insights to reveal the deep resonance of your true soulmate.
                </p>
              </div>

              <div className="space-y-2.5 pt-2">
                <div className="flex items-center gap-3 text-xs text-neutral-700">
                  <span className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-xs">✨</span>
                  <span>Hand-crafted pencil portrait &amp; comprehensive personality reading.</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-neutral-700">
                  <span className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-xs">🔒</span>
                  <span>Private, confidential, and tailored to your energy.</span>
                </div>
              </div>
            </div>
          )}
        </TransitionShell>
      )}

      {/* Transition-1 (Figma 102:304) */}
      {step === 1 && (
        <TransitionShell
          step={1}
          badge={
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-[#f5f0ff] text-[#7c3aed] text-xs font-medium">
              <span className="w-2 h-2 rounded-full bg-[#7c3aed]" />
              <span>Sketching now</span>
            </div>
          }
          title="Your artist has started"
          illustration={
            <Image
              src="/images/transitions/artist-sketching.png"
              alt="Artist sketching soulmate portrait"
              width={256}
              height={320}
              className="w-[240px] h-auto object-contain drop-shadow-sm"
              priority
            />
          }
          onContinue={handleContinue}
        />
      )}

      {/* Transition-2 (Figma 102:320 & COPY-02) */}
      {step === 2 && (
        <TransitionShell
          step={2}
          title="Awesome!"
          subtitle={transition2Subtitle}
          illustration={
            <Image
              src="/images/transitions/target-bullseye.png"
              alt="Target bullseye icon"
              width={128}
              height={128}
              className="w-28 h-28 object-contain my-3"
              priority
            />
          }
          onContinue={handleContinue}
        />
      )}

      {/* Transition-3 (Figma 102:345 & DEV-SPEC §5.5) */}
      {step === 3 && (
        <TransitionShell
          step={3}
          title="Good to know!"
          subtitle={
            <span>
              Based on intuitive guidance, many{" "}
              <strong className="text-[#6b38c2]">{transition3Data.zodiacLabel}</strong>{" "}
              {transition3Data.decisionCopy}
            </span>
          }
          illustration={
            <Image
              src="/images/transitions/scale-balance.png"
              alt="Zodiac balance scale icon"
              width={120}
              height={120}
              className="w-28 h-28 object-contain my-3"
              priority
            />
          }
          onContinue={handleContinue}
        />
      )}

      {/* Transition-4 (Figma 102:372 & COPY-03) */}
      {step === 4 && (
        <TransitionShell
          step={4}
          title={customTitle4 || TRANSITION_4_STATIC_COPY.title}
          subtitle={customSubtitle4 || TRANSITION_4_STATIC_COPY.subtitle}
          illustration={
            <Image
              src="/images/transitions/heart-hands.png"
              alt="Hands holding heart icon"
              width={128}
              height={128}
              className="w-28 h-28 object-contain my-3"
              priority
            />
          }
          onContinue={handleContinue}
        />
      )}

      {/* Transition-5 (Figma 102:386 & Experiential Progress) */}
      {step === 5 && (
        <TransitionShell
          step={5}
          title="Connecting to the universe"
          continueLabel="See Results"
          onContinue={handleContinue}
        >
          <Transition5Progress />
        </TransitionShell>
      )}

      {/* Sequential Interstitial Modals (Figma 102:425, 102:466, 102:445) */}
      {activePopup && (
        <InterstitialModal
          type={activePopup}
          isOpen={true}
          onAnswer={handleModalAnswer}
        />
      )}
    </>
  );
}

export default function SoulmateLoadingPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">Loading...</div>}>
      <LoadingContent />
    </Suspense>
  );
}
