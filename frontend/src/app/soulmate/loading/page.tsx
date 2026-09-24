"use client";

import React, { useState, Suspense } from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import {
  TransitionShell,
  Transition5Progress,
  InterstitialModal,
  InterstitialType,
  getNextInterstitialPopup,
} from "@/soulmate/components/transition";
import {
  getTransition2Copy,
  getTransition3Copy,
  TRANSITION_4_STATIC_COPY,
} from "@/soulmate/components/transition/copy";
import {
  createSession,
  getCurrentSession,
  continueTransition,
  submitInterstitialAnswer,
  getFlowState,
  isSessionMissingError,
  FlowStateResponse,
} from "@/soulmate/api/session";
import { getSafeUserErrorMessage } from "@/soulmate/api/errors";

function LoadingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // State for sequential Transition-5 popups, session, and flow state
  const [activePopup, setActivePopup] = useState<InterstitialType | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<{ message: string; onRetry?: () => void } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [flowState, setFlowState] = useState<FlowStateResponse | null>(null);

  // Step 0 through 5 from query param, defaulting to 0
  const stepParam = parseInt(searchParams.get("step") || "0", 10);
  const step = isNaN(stepParam) || stepParam < 0 || stepParam > 5 ? 0 : stepParam;

  // Marketing Claims Compliance Gate (DEV-SPEC §21, LEGAL-01)
  const isProduction = process.env.NODE_ENV === "production";
  const shouldShowMarketingClaims =
    !isProduction &&
    (searchParams.get("claims") === "true" ||
      process.env.NEXT_PUBLIC_ENABLE_MARKETING_CLAIMS === "true");

  const isFixtureMode = !isProduction && searchParams.get("fixture") === "true";

  // Dynamic copy injection parameters
  const qualityParam = searchParams.get("quality");
  const serverTransition2Body =
    typeof flowState?.step_metadata?.body === "string"
      ? (flowState.step_metadata.body as string)
      : null;
  const transition2Subtitle: string =
    serverTransition2Body ||
    getTransition2Copy(
      qualityParam || (flowState?.step_metadata?.selected_option as string | undefined)
    );
  const customTitle4 = searchParams.get("title");
  const customSubtitle4 = searchParams.get("subtitle");

  // Transition-3 Zodiac & Decision Style (DEV-SPEC §5.5)
  const zodiacParam = searchParams.get("zodiac") || "Virgo Sun";
  const decisionParam = searchParams.get("decision") || "both";
  const transition3Data = getTransition3Copy({
    zodiacLabel: zodiacParam,
    decisionStyle: decisionParam,
  });

  // Bootstrap session and flow state if in live mode
  React.useEffect(() => {
    if (isFixtureMode) return;
    let isCancelled = false;
    async function initSession() {
      setError(null);
      let sId: string | null = null;
      try {
        const sess = await getCurrentSession();
        if (!isCancelled) {
          setSessionId(sess.session_id);
          sId = sess.session_id;
        }
      } catch (err: unknown) {
        if (isSessionMissingError(err)) {
          try {
            const created = await createSession();
            if (!isCancelled) {
              setSessionId(created.session_id);
              sId = created.session_id;
            }
          } catch (createErr: unknown) {
            if (!isCancelled) {
              const msg = getSafeUserErrorMessage(createErr);
              setError({ message: msg, onRetry: () => initSession() });
            }
            return;
          }
        } else {
          // Transient network failure or 5xx server error -> retain session & offer retry
          if (!isCancelled) {
            const msg = getSafeUserErrorMessage(err);
            setError({ message: msg, onRetry: () => initSession() });
          }
          return;
        }
      }

      if (sId && !isCancelled) {
        try {
          const state = await getFlowState(sId);
          if (!isCancelled) {
            setFlowState(state);
          }
        } catch {
          // Flow state metadata fallback
        }
      }
    }
    initSession();
    return () => {
      isCancelled = true;
    };
  }, [isFixtureMode]);

  const handleContinue = async () => {
    // Note: Fixture mode (?fixture=true in dev) is an isolated static preview
    // for UI inspection only, and intentionally bypasses the backend flow state machine.
    // In live mode (standard dev and all production), continueTransition() strictly queries
    // the server resolver to advance authoritatively per DEV-SPEC §5.
    if (isFixtureMode || !sessionId) {
      switch (step) {
        case 0:
          router.push("/soulmate/quiz?code=q02");
          break;
        case 1:
          router.push("/soulmate/quiz?code=q07");
          break;
        case 2:
          router.push("/soulmate/quiz?code=q08");
          break;
        case 3:
          router.push("/soulmate/quiz?code=q11");
          break;
        case 4:
          router.push("/soulmate/quiz?code=q12");
          break;
        case 5:
          setActivePopup("spiritual");
          break;
        default:
          router.push("/soulmate");
      }
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const res = await continueTransition(sessionId, `transition_${step}`);
      if (res.flow_state) {
        setFlowState(res.flow_state);
      }
      if (step === 5) {
        setActivePopup("spiritual");
      } else if (res.next_step.startsWith("q")) {
        router.push(`/soulmate/quiz?code=${res.next_step}`);
      } else if (res.next_step.startsWith("transition_")) {
        const nextStepNum = res.next_step.replace("transition_", "");
        router.push(`/soulmate/loading?step=${nextStepNum}`);
      } else {
        router.push("/soulmate/quiz");
      }
    } catch (err: unknown) {
      // Do NOT advance on error; retain current screen and show retryable error (DEV-SPEC §6, Finding 2)
      const msg = err instanceof Error ? err.message : "Failed to continue transition";
      setError({
        message: msg,
        onRetry: () => handleContinue(),
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleModalAnswer = async (answer: boolean) => {
    if (!activePopup) return;

    if (isFixtureMode || !sessionId) {
      const nextPopup = getNextInterstitialPopup(activePopup);
      if (nextPopup) {
        setActivePopup(nextPopup);
      } else {
        setActivePopup(null);
        const params = new URLSearchParams();
        ["preferred_partner_gender", "partner_gender", "user_gender", "age_range", "ethnicity"].forEach((key) => {
          const val = searchParams.get(key);
          if (val) params.set(key, val);
        });
        const query = params.toString();
        router.push(`/soulmate/email${query ? `?${query}` : ""}`);
      }
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const codeMap: Record<InterstitialType, "spiritual_person" | "familiar_psychic_artistry" | "warning_response"> = {
        spiritual: "spiritual_person",
        psychic_artistry: "familiar_psychic_artistry",
        warning: "warning_response",
      };
      const code = codeMap[activePopup];
      const val = activePopup === "warning" ? (answer ? "yes" : "no") : answer;
      await submitInterstitialAnswer(sessionId, code, val);

      const nextPopup = getNextInterstitialPopup(activePopup);
      if (nextPopup) {
        setActivePopup(nextPopup);
      } else {
        setActivePopup(null);
        const params = new URLSearchParams();
        ["preferred_partner_gender", "partner_gender", "user_gender", "age_range", "ethnicity"].forEach((key) => {
          const val = searchParams.get(key);
          if (val) params.set(key, val);
        });
        const query = params.toString();
        router.push(`/soulmate/email${query ? `?${query}` : ""}`);
      }
    } catch (err: unknown) {
      // Do NOT advance on error; retain current modal and show retryable error (Finding 2)
      const msg = err instanceof Error ? err.message : "Failed to save answer";
      setError({
        message: msg,
        onRetry: () => handleModalAnswer(answer),
      });
    } finally {
      setIsLoading(false);
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
          loading={isLoading}
          error={error}
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
          loading={isLoading}
          error={error}
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
          loading={isLoading}
          error={error}
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
              <strong className="text-[#6b38c2]">
                {(flowState?.step_metadata?.zodiac_label as string | undefined) || transition3Data.zodiacLabel}
              </strong>{" "}
              {(flowState?.step_metadata?.decision_copy as string | undefined) || transition3Data.decisionCopy}
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
          loading={isLoading}
          error={error}
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
              src="/images/transitions/heart-support.png"
              alt="Hands holding heart icon"
              width={128}
              height={128}
              className="w-28 h-28 object-contain my-3"
              priority
            />
          }
          onContinue={handleContinue}
          loading={isLoading}
          error={error}
        />
      )}

      {/* Transition-5 (Figma 102:386 & Experiential Progress) */}
      {step === 5 && (
        <TransitionShell
          step={5}
          title="Connecting to the universe"
          continueLabel="See Results"
          onContinue={handleContinue}
          loading={isLoading}
          error={error}
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
          loading={isLoading}
          error={error}
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
