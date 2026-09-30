"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { QuizShell, QuizNextButton, OptionCard, RadioGroup, WheelDatePicker } from "@/soulmate/components/quiz";
import {
  createSession,
  getCurrentSession,
  getSession,
  submitAnswer,
  navigateBack,
  getQuizConfig,
  isSessionMissingError,
  QuizConfig,
  SavedAnswerDetail,
  SessionCurrentResponse,
} from "@/soulmate/api/session";
import { getSafeUserErrorMessage } from "@/soulmate/api/errors";
import { FlowShellFallback } from "@/soulmate/components/flow/FlowShellFallback";
import { useSharedFlow } from "@/soulmate/components/flow/SharedFlowContext";
import { prefetchFlowRoute, flowRouteForStep } from "@/soulmate/components/flow/flowTargets";
import type { PreparedStepEntry } from "@/soulmate/components/flow/stepPreparation";
import { trackOnce, trackSoulmateEvent } from "@/soulmate/analytics";
import quizData from "@/soulmate/quiz/soulmate-quiz-v1.json";

type PreviewQuestionType = "single" | "date" | "multi";

/**
 * Shallow URL sync for question-to-question movement (Next.js-sanctioned
 * window.history.replaceState): keeps ?code= deep-linkable without a router
 * navigation — no RSC refetch, no Suspense swap, no client-state loss. The
 * in-product Back button remains server-authoritative via navigateBack.
 */
function syncQuestionUrl(code: string) {
  if (typeof window === "undefined") return;
  window.history.replaceState(null, "", `/soulmate/quiz?code=${code}`);
}

function QuizPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sharedFlow = useSharedFlow();

  const isProduction = process.env.NODE_ENV === "production";
  // Fixture mode is strictly isolated and only available in development when ?fixture=true
  const isFixtureMode = !isProduction && searchParams.get("fixture") === "true";
  const showDevToolbar = !isProduction && isFixtureMode;

  const codeParam = searchParams.get("code");
  // Bootstrap reads the entry-time ?code= once; question movement updates the
  // URL shallowly afterwards, so the bootstrap must never re-run on it.
  const initialCodeRef = useRef(codeParam);

  // In fixture mode, allow switching between the three core question types (Single, Date, Multi)
  const [currentType, setCurrentType] = useState<PreviewQuestionType>("single");

  // Active question code (defaulting to query code or q02)
  const [activeStepCode, setActiveStepCode] = useState<string>(() => {
    if (codeParam && quizData.questions.some((q) => q.code === codeParam)) {
      return codeParam;
    }
    return "q02";
  });

  // State management for session & answers
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionCurrentResponse | null>(null);

  // Form values for current question
  const [singleValue, setSingleValue] = useState<string>("female");
  const [dateValue, setDateValue] = useState<string>("1995-06-15");
  // Wheel columns are mid-gesture (batch 4 §8 item 5): Next stays disabled
  // until every column settles and the settled draft is committed.
  const [wheelMoving, setWheelMoving] = useState<boolean>(false);
  const [multiValues, setMultiValues] = useState<string[]>([
    "building_a_family",
    "traveling_the_world",
  ]);

  // Loading & In-flight locking (Acceptance: rapid taps are locked while request is in flight)
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  // Back navigation pending: current question stays rendered (controls disabled) —
  // the full-screen skeleton is reserved for real entry/loading, not step moves.
  const [isBackPending, setIsBackPending] = useState<boolean>(false);
  const [error, setError] = useState<{ message: string; onRetry?: () => void } | null>(null);

  // Local submitting hint (batch 2): a small non-blocking chip appears only when
  // a submission takes longer than ~400ms. The timer controls the hint's
  // appearance only — step advance timing stays server-driven (§4.2). Cleared on
  // success, failure, and unmount.
  const [showSubmitHint, setShowSubmitHint] = useState<boolean>(false);
  const submitHintTimer = useRef<number | null>(null);
  const clearSubmitHint = () => {
    if (submitHintTimer.current !== null) {
      clearTimeout(submitHintTimer.current);
      submitHintTimer.current = null;
    }
    setShowSubmitHint(false);
  };
  const startSubmitHint = () => {
    clearSubmitHint();
    submitHintTimer.current = window.setTimeout(() => {
      setShowSubmitHint(true);
    }, 400);
  };
  useEffect(() => {
    return () => clearSubmitHint();
  }, []);

  const questionStartTime = useRef<number>(Date.now());
  // §18.1 quiz funnel tracking state (one-shot start + per-question duration base)
  const quizStartedTrackedRef = useRef(false);
  const quizStartedAtRef = useRef<number | null>(null);
  const activeQuestionRef = useRef<string | null>(null);

  // Dynamic quiz configuration matching the session's pinned version (DEV-SPEC §15.2)
  const [activeQuizConfig, setActiveQuizConfig] = useState<QuizConfig>(quizData as QuizConfig);

  // Current active question definition from active quiz config
  const currentQuestion =
    activeQuizConfig.questions.find((q) => q.code === activeStepCode) ||
    activeQuizConfig.questions[0];

  // §18.1 quiz_started (once per session) + question_view (per rendered question).
  // Fires only for live question rendering — fixture preview and loading skeletons
  // stay untracked so funnel data reflects real question views.
  React.useEffect(() => {
    if (isFixtureMode || isLoading) return;
    if (activeQuestionRef.current === activeStepCode) return;
    activeQuestionRef.current = activeStepCode;
    if (!quizStartedTrackedRef.current) {
      quizStartedTrackedRef.current = true;
      quizStartedAtRef.current = Date.now();
      trackOnce("quiz_started", {
        name: "soulmate_quiz_started",
        properties: { quiz_version: sessionData?.quiz_version ?? null },
      });
    }
    trackSoulmateEvent({
      name: "soulmate_question_view",
      properties: { question_code: activeStepCode },
    });
  }, [activeStepCode, isFixtureMode, isLoading, sessionData]);

  // Helper to pre-populate answers for a question (Acceptance: refresh at any question restores answer/state)
  const restoreAnswerForQuestion = (qCode: string, savedAnswer?: SavedAnswerDetail, config?: QuizConfig) => {
    const qList = config ? config.questions : activeQuizConfig.questions;
    const qDef = qList.find((q) => q.code === qCode);
    if (!qDef) return;

    if (qDef.type === "single") {
      const val = savedAnswer?.value ?? (savedAnswer?.answer as { value?: string })?.value;
      setSingleValue(typeof val === "string" ? val : "");
    } else if (qDef.type === "date") {
      const val = savedAnswer?.value ?? (savedAnswer?.answer as { value?: string })?.value;
      setDateValue(typeof val === "string" ? val : "");
    } else if (qDef.type === "multi") {
      const vals = savedAnswer?.values ?? (savedAnswer?.answer as { values?: string[] })?.values;
      setMultiValues(
        Array.isArray(vals) ? vals.filter((x): x is string => typeof x === "string") : []
      );
    }
  };

  // 1. Session Bootstrap & State Recovery on Mount (DEV-SPEC §6, §15.1, SP-201, SP-207)
  useEffect(() => {
    if (isFixtureMode) {
      // In fixture mode, set default preview values without network calls
      setSingleValue("female");
      setDateValue("1995-06-15");
      setMultiValues(["building_a_family", "traveling_the_world"]);
      return;
    }

    let isCancelled = false;

    async function bootstrapSession() {
      // Warm path (persistent /soulmate shared flow state): the layout-level
      // provider already holds this browser's session and the session-pinned
      // quiz config from an earlier funnel page — hydrate locally with zero
      // network and no skeleton swap, so entering the quiz from a transition
      // renders the question immediately.
      if (sharedFlow.sessionId && sharedFlow.sessionData && sharedFlow.quizConfig) {
        const urlCode = initialCodeRef.current;
        const confirmed = sharedFlow.confirmedStep;
        // Batch 3 §6.4 + audit P1: warm adoption requires the server-confirmed
        // step to EQUAL the URL code (a normal client-side advance). Any other
        // case — refresh, history restore, edited/foreign deep link, missing
        // confirmation — falls through to the cold server-recovery path below,
        // which re-queries the server and corrects the URL from its verdict.
        if (confirmed && confirmed.startsWith("q") && confirmed === urlCode) {
          setSessionId(sharedFlow.sessionId);
          setSessionData(sharedFlow.sessionData);
          setActiveQuizConfig(sharedFlow.quizConfig);
          setActiveStepCode(confirmed);
          questionStartTime.current = Date.now();
          restoreAnswerForQuestion(
            confirmed,
            sharedFlow.sessionData.answers[confirmed],
            sharedFlow.quizConfig
          );
          return;
        }
        // Mismatch (or no confirmation): fall through to cold recovery. The
        // provider is re-populated from the fresh server response there.
      }

      setIsLoading(true);
      setError(null);

      try {
        let currentSess: SessionCurrentResponse;
        try {
          // Attempt cookie-based session recovery
          currentSess = await getCurrentSession();
        } catch (err: unknown) {
          // Superseded mount (StrictMode double-invoke, fast remount) must not
          // fire its own createSession — two concurrent creates leave the
          // cookie and the state on different sessions (ownership 403 later).
          if (isCancelled) return;
          if (isSessionMissingError(err)) {
            // Genuinely no active/valid session exists (401, 403, 404) -> initialize fresh session
            const created = await createSession();
            currentSess = await getSession(created.session_id);
          } else {
            // Transient network failure or 5xx server error -> retain session & offer retry
            if (!isCancelled) {
              const msg = getSafeUserErrorMessage(err);
              setError({ message: msg, onRetry: () => bootstrapSession() });
              setIsLoading(false);
            }
            return;
          }
        }

        if (isCancelled) return;

        setSessionId(currentSess.session_id);
        setSessionData(currentSess);
        // Persist into the shared flow state (session + answers cache) so the
        // next funnel page hydrates without re-running its bootstrap.
        sharedFlow.setSession(currentSess.session_id, currentSess);

        const serverStep = currentSess.current_step;

        // If server indicates we are at a transition screen, route to /soulmate/loading
        if (serverStep.startsWith("transition_")) {
          const stepNum = serverStep.replace("transition_", "");
          router.push(`/soulmate/loading?step=${stepNum}`);
          return;
        }

        // If server indicates an interstitial popup or email
        if (
          ["spiritual_person", "familiar_psychic_artistry", "warning_response"].includes(
            serverStep
          )
        ) {
          router.push(`/soulmate/loading?step=5`);
          return;
        }
        if (serverStep === "email") {
          router.push("/soulmate/email");
          return;
        }

        // Fetch session-pinned immutable quiz configuration (DEV-SPEC §15.2, Finding 4)
        let loadedConfig = activeQuizConfig;
        try {
          const config = await getQuizConfig(currentSess.quiz_version);
          if (!isCancelled) {
            setActiveQuizConfig(config);
            loadedConfig = config;
            // Persist into the shared flow state so the next funnel page
            // hydrates without re-running this bootstrap.
            sharedFlow.setQuizConfig(config);
          }
        } catch {
          // Keep local fallback if offline
        }

        // Authoritative step resolution (DEV-SPEC §6): the server's persisted
        // current_step wins over a deep-linked/stale ?code= on refresh; an
        // inconsistent URL is corrected below rather than steering the session.
        const urlCode = initialCodeRef.current;
        const targetStep = serverStep.startsWith("q")
          ? serverStep
          : urlCode && loadedConfig.questions.some((q) => q.code === urlCode)
          ? urlCode
          : "q02";

        if (urlCode !== targetStep) {
          syncQuestionUrl(targetStep);
        }

        setActiveStepCode(targetStep);
        questionStartTime.current = Date.now();

        // Restore saved answer if present (Acceptance: refresh at any question restores answer/state)
        const savedAnswer = currentSess.answers[targetStep];
        restoreAnswerForQuestion(targetStep, savedAnswer, loadedConfig);
      } catch (err: unknown) {
        if (isCancelled) return;
        const msg = err instanceof Error ? err.message : "Failed to load session";
        setError({
          message: msg,
          onRetry: () => bootstrapSession(),
        });
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    bootstrapSession();

    return () => {
      isCancelled = true;
    };
  }, [isFixtureMode, router]);

  // §18.1 quiz_completed: the quiz ends when an answer resolves to any
  // non-question step (transition/interstitial/email). One-shot per session.
  const trackQuizCompleted = () => {
    const total =
      quizStartedAtRef.current != null ? Date.now() - quizStartedAtRef.current : null;
    trackOnce("quiz_completed", {
      name: "soulmate_quiz_completed",
      properties: { total_duration: total },
    });
  };

  // Helper to advance to next authoritative step returned by backend
  const advanceToNextStep = (nextStep: string) => {
    clearSubmitHint();
    setIsSubmitting(false);
    questionStartTime.current = Date.now();

    if (nextStep.startsWith("transition_")) {
      const stepNum = nextStep.replace("transition_", "");
      router.push(`/soulmate/loading?step=${stepNum}`);
    } else if (nextStep.startsWith("q")) {
      // Pure client-state advance + shallow URL sync: no router navigation, so
      // the rendered quiz is never swapped for a Suspense fallback or skeleton.
      setActiveStepCode(nextStep);
      syncQuestionUrl(nextStep);
      const nextSaved = sessionData?.answers[nextStep];
      restoreAnswerForQuestion(nextStep, nextSaved);
    } else if (
      ["spiritual_person", "familiar_psychic_artistry", "warning_response"].includes(nextStep)
    ) {
      router.push(`/soulmate/loading?step=5`);
    } else if (nextStep === "email") {
      router.push("/soulmate/email");
    } else {
      router.push("/soulmate");
    }
  };

  // Component-lifetime guard (audit P1): async continuations (dwell, answer
  // confirmation, preparation) must never act after the page unmounted.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const dwell = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

  // Batch 3 §6.3.3 + audit P2: navigation to a transition target happens ONLY
  // after its prepared metadata is validated (session + current_step). On
  // preparation failure the current content stays and Retry re-prepares —
  // the saved answer is never resubmitted. If the server has moved on (e.g.
  // another tab), route to its ACTUAL step instead of the expected one.
  const advanceAfterPreparation = (entry: PreparedStepEntry, expectedStep: string) => {
    if (entry.status !== "ready" || !entry.flowState) {
      clearSubmitHint();
      setIsSubmitting(false);
      setError({
        message: "Still connecting to the next step. Tap retry to keep loading.",
        onRetry: () => void retryAdvance(expectedStep),
      });
      return;
    }
    if (entry.flowState.session_id !== sessionId) {
      // Preparation belongs to a superseded session — abort without navigating.
      clearSubmitHint();
      setIsSubmitting(false);
      return;
    }
    if (entry.flowState.current_step !== expectedStep) {
      clearSubmitHint();
      setIsSubmitting(false);
      const actual = flowRouteForStep(entry.flowState.current_step);
      if (actual) router.push(actual);
      else advanceToNextStep(expectedStep);
      return;
    }
    advanceToNextStep(expectedStep);
  };

  const retryAdvance = async (step: string) => {
    if (!sessionId) return;
    setError(null);
    setIsSubmitting(true);
    startSubmitHint();
    const seq = sharedFlow.bumpOp();
    const entry = await sharedFlow.ensurePrepared(sessionId, step);
    if (!sharedFlow.isCurrentOp(seq) || !mountedRef.current) {
      clearSubmitHint();
      setIsSubmitting(false);
      return;
    }
    advanceAfterPreparation(entry, step);
  };

  // 2. Single-Select Option Click Handler (DEV-SPEC §4.2)
  const handleSingleOptionClick = async (optionCode: string) => {
    // Rapid taps locking (Acceptance)
    if (isSubmitting || isLoading || isBackPending) return;

    setSingleValue(optionCode);
    setError(null);

    // In fixture mode, run mock timer advance
    if (isFixtureMode) {
      setIsSubmitting(true);
      setTimeout(() => {
        setIsSubmitting(false);
        if (currentType === "single") {
          setCurrentType("date");
        }
      }, 200);
      return;
    }

    if (!sessionId) return;

    setIsSubmitting(true);
    startSubmitHint();
    // Local op sequence (batch 3 §6.1): a newer local operation (Back, another
    // submit) supersedes this submission's async results.
    const seq = sharedFlow.bumpOp();
    const duration = Math.max(0, Date.now() - questionStartTime.current);

    try {
      const res = await submitAnswer(sessionId, activeStepCode, {
        value: optionCode,
        duration_ms: duration,
      });
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded locally — discard the stale confirmation
      }

      // Server-confirmed answers snapshot (batch 3 §6.2.1): immutable update in
      // the local copy and the shared provider — never a direct mutation.
      const savedAnswer: SavedAnswerDetail = {
        question_code: activeStepCode,
        answer: { value: optionCode },
        value: optionCode,
        answered_at: new Date().toISOString(),
      };
      setSessionData((prev) =>
        prev ? { ...prev, answers: { ...prev.answers, [activeStepCode]: savedAnswer } } : prev
      );
      sharedFlow.confirmAnswer(activeStepCode, savedAnswer, res.next_step, sessionId);

      // §18.1: save success, option code only (§18.2 — never the raw answer text)
      trackSoulmateEvent({
        name: "soulmate_question_answered",
        properties: {
          question_code: activeStepCode,
          option_codes: [optionCode],
          duration_ms: duration,
        },
      });
      if (!res.next_step.startsWith("q")) trackQuizCompleted();

      prefetchFlowRoute(router, res.next_step);

      // Batch 3 §6.3.2 + audit P2: the transition target's metadata is prepared
      // in parallel with the 150ms dwell; navigation waits for BOTH and only
      // proceeds on a session/step-validated preparation (§6.3.3).
      if (res.next_step.startsWith("transition_")) {
        const prep = sharedFlow.ensurePrepared(sessionId, res.next_step);
        const [, entry] = await Promise.all([dwell(150), prep]);
        if (!sharedFlow.isCurrentOp(seq) || !mountedRef.current) {
          clearSubmitHint();
          setIsSubmitting(false);
          return; // superseded or unmounted — do not advance
        }
        advanceAfterPreparation(entry, res.next_step);
      } else {
        // 150ms visual selection feedback before advancing (DEV-SPEC §4.2)
        await dwell(150);
        if (!sharedFlow.isCurrentOp(seq) || !mountedRef.current) {
          clearSubmitHint();
          setIsSubmitting(false);
          return; // superseded or unmounted — do not advance
        }
        advanceToNextStep(res.next_step);
      }
    } catch (err: unknown) {
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded — keep the current UI, never surface a stale error
      }
      clearSubmitHint();
      setIsSubmitting(false);
      const msg = err instanceof Error ? err.message : "Failed to save answer";
      setError({
        message: msg,
        onRetry: () => handleSingleOptionClick(optionCode),
      });
    }
  };

  // 3. Date Submit Handler (DEV-SPEC §4.4)
  const handleDateSubmit = async () => {
    if (isSubmitting || isLoading || isBackPending || !dateValue) return;

    setError(null);

    if (isFixtureMode) {
      setIsSubmitting(true);
      setTimeout(() => {
        setIsSubmitting(false);
        setCurrentType("multi");
      }, 200);
      return;
    }

    if (!sessionId) return;

    setIsSubmitting(true);
    startSubmitHint();
    const seq = sharedFlow.bumpOp();
    const duration = Math.max(0, Date.now() - questionStartTime.current);

    try {
      const res = await submitAnswer(sessionId, activeStepCode, {
        value: dateValue,
        duration_ms: duration,
      });
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded locally — discard the stale confirmation
      }

      // Server-confirmed answers snapshot (immutable, batch 3 §6.2.1)
      const savedAnswer: SavedAnswerDetail = {
        question_code: activeStepCode,
        answer: { value: dateValue },
        value: dateValue,
        answered_at: new Date().toISOString(),
      };
      setSessionData((prev) =>
        prev ? { ...prev, answers: { ...prev.answers, [activeStepCode]: savedAnswer } } : prev
      );
      sharedFlow.confirmAnswer(activeStepCode, savedAnswer, res.next_step, sessionId);

      // §18.2: the raw date value (DOB) is PII — the analytics event carries
      // the question + duration only, with NO option_codes content.
      trackSoulmateEvent({
        name: "soulmate_question_answered",
        properties: {
          question_code: activeStepCode,
          option_codes: [],
          duration_ms: duration,
        },
      });
      if (!res.next_step.startsWith("q")) trackQuizCompleted();

      prefetchFlowRoute(router, res.next_step);

      // Audit P2: transition targets wait for their prepared metadata and a
      // session/step validation before navigation (§6.3.3).
      if (res.next_step.startsWith("transition_")) {
        const entry = await sharedFlow.ensurePrepared(sessionId, res.next_step);
        if (!sharedFlow.isCurrentOp(seq) || !mountedRef.current) {
          clearSubmitHint();
          setIsSubmitting(false);
          return; // superseded or unmounted — do not advance
        }
        advanceAfterPreparation(entry, res.next_step);
      } else {
        advanceToNextStep(res.next_step);
      }
    } catch (err: unknown) {
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded — keep the current UI
      }
      clearSubmitHint();
      setIsSubmitting(false);
      const msg = err instanceof Error ? err.message : "Failed to save birth date";
      setError({
        message: msg,
        onRetry: () => handleDateSubmit(),
      });
    }
  };

  // 4. Multi-Select Submit Handler (DEV-SPEC §4.3)
  const handleMultiSubmit = async () => {
    if (isSubmitting || isLoading || isBackPending || multiValues.length === 0) return;

    setError(null);

    if (isFixtureMode) {
      setIsSubmitting(true);
      setTimeout(() => {
        setIsSubmitting(false);
        router.push("/soulmate/loading?step=5");
      }, 200);
      return;
    }

    if (!sessionId) return;

    setIsSubmitting(true);
    startSubmitHint();
    const seq = sharedFlow.bumpOp();
    const duration = Math.max(0, Date.now() - questionStartTime.current);

    try {
      const res = await submitAnswer(sessionId, activeStepCode, {
        values: multiValues,
        duration_ms: duration,
      });
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded locally — discard the stale confirmation
      }

      // Server-confirmed answers snapshot (immutable, batch 3 §6.2.1)
      const savedAnswer: SavedAnswerDetail = {
        question_code: activeStepCode,
        answer: { values: multiValues },
        values: multiValues,
        answered_at: new Date().toISOString(),
      };
      setSessionData((prev) =>
        prev ? { ...prev, answers: { ...prev.answers, [activeStepCode]: savedAnswer } } : prev
      );
      sharedFlow.confirmAnswer(activeStepCode, savedAnswer, res.next_step, sessionId);

      // §18.1: option codes only (§18.2 — never free text)
      trackSoulmateEvent({
        name: "soulmate_question_answered",
        properties: {
          question_code: activeStepCode,
          option_codes: multiValues,
          duration_ms: duration,
        },
      });
      if (!res.next_step.startsWith("q")) trackQuizCompleted();

      prefetchFlowRoute(router, res.next_step);

      // Audit P2: transition targets wait for their prepared metadata and a
      // session/step validation before navigation (§6.3.3).
      if (res.next_step.startsWith("transition_")) {
        const entry = await sharedFlow.ensurePrepared(sessionId, res.next_step);
        if (!sharedFlow.isCurrentOp(seq) || !mountedRef.current) {
          clearSubmitHint();
          setIsSubmitting(false);
          return; // superseded or unmounted — do not advance
        }
        advanceAfterPreparation(entry, res.next_step);
      } else {
        advanceToNextStep(res.next_step);
      }
    } catch (err: unknown) {
      if (!sharedFlow.isCurrentOp(seq)) {
        clearSubmitHint();
        setIsSubmitting(false);
        return; // superseded — keep the current UI
      }
      clearSubmitHint();
      setIsSubmitting(false);
      const msg = err instanceof Error ? err.message : "Failed to save choices";
      setError({
        message: msg,
        onRetry: () => handleMultiSubmit(),
      });
    }
  };

  // 5. Back Navigation (DEV-SPEC §4.2, SP-203, SP-207)
  const handleBack = async () => {
    if (isSubmitting || isLoading || isBackPending) return;

    if (isFixtureMode) {
      if (currentType === "multi") {
        setCurrentType("date");
      } else if (currentType === "date") {
        setCurrentType("single");
      } else {
        router.push("/soulmate");
      }
      return;
    }

    if (!sessionId) {
      router.push("/soulmate");
      return;
    }

    // In-flight back keeps the CURRENT question rendered (controls disabled)
    // and switches only when the server-authoritative response arrives.
    setIsBackPending(true);
    setError(null);
    // Any in-flight answer confirmation is superseded by this back navigation.
    const seq = sharedFlow.bumpOp();

    try {
      const flowState = await navigateBack(sessionId);
      const prevStep = flowState.current_step;
      if (!sharedFlow.isCurrentOp(seq)) return; // superseded — never apply a stale back
      // Server-confirmed step (batch 3 §6.2.4): prunes preparations that no
      // longer match the step the session actually sits on.
      sharedFlow.confirmStep(prevStep);

      // §18.1 back navigation (to_q is null when back leaves the question flow)
      trackSoulmateEvent({
        name: "soulmate_quiz_back",
        properties: { from_q: activeStepCode, to_q: prevStep.startsWith("q") ? prevStep : null },
      });

      if (prevStep.startsWith("transition_")) {
        const stepNum = prevStep.replace("transition_", "");
        router.push(`/soulmate/loading?step=${stepNum}`);
        return;
      }

      if (prevStep.startsWith("q")) {
        setActiveStepCode(prevStep);
        syncQuestionUrl(prevStep);
        const saved = sessionData?.answers[prevStep];
        restoreAnswerForQuestion(prevStep, saved);
      } else {
        router.push("/soulmate");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to navigate back";
      setError({
        message: msg,
        onRetry: () => handleBack(),
      });
    } finally {
      setIsBackPending(false);
    }
  };

  // Determine effective rendering mode (fixture vs live question)
  const effectiveType = isFixtureMode ? currentType : currentQuestion.type;

  return (
    <div className="relative">
      {/* Local submitting hint (batch 2): appears only after ~400ms of an
          in-flight submission; non-blocking, no layout shift, never gates the
          server-driven step advance. */}
      {showSubmitHint && (
        <div
          data-testid="quiz-submit-hint"
          aria-live="polite"
          className="fixed bottom-[calc(1rem+var(--sp-safe-bottom))] left-0 right-0 z-30 flex justify-center pointer-events-none"
        >
          <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#2c2c2e]/80 text-white text-xs font-medium shadow-md">
            <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Saving…
          </span>
        </div>
      )}

      {/* Fixture banner (only displayed in development when fixture=true) */}
      {!isProduction && isFixtureMode && (
        <div
          data-testid="quiz-fixture-banner"
          className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
        >
          [Demo Preview (Fixture Shell)]
        </div>
      )}

      {/* Dev Switcher for testing all three question types in fixture shell (M-1) */}
      {showDevToolbar && (
        <div
          data-testid="quiz-dev-toolbar"
          className="absolute top-2 right-4 z-50 flex gap-1 bg-white/80 backdrop-blur-xs p-1 rounded-lg text-[10px] text-neutral-600 border border-neutral-200"
        >
          <button
            type="button"
            data-testid="quiz-switcher-single"
            onClick={() => setCurrentType("single")}
            className={`px-1.5 py-0.5 rounded ${
              currentType === "single"
                ? "bg-purple-600 text-white font-semibold"
                : "hover:bg-neutral-100"
            }`}
          >
            Single
          </button>
          <button
            type="button"
            data-testid="quiz-switcher-date"
            onClick={() => setCurrentType("date")}
            className={`px-1.5 py-0.5 rounded ${
              currentType === "date"
                ? "bg-purple-600 text-white font-semibold"
                : "hover:bg-neutral-100"
            }`}
          >
            Date
          </button>
          <button
            type="button"
            data-testid="quiz-switcher-multi"
            onClick={() => setCurrentType("multi")}
            className={`px-1.5 py-0.5 rounded ${
              currentType === "multi"
                ? "bg-purple-600 text-white font-semibold"
                : "hover:bg-neutral-100"
            }`}
          >
            Multi
          </button>
        </div>
      )}

      {/* Single Choice Question Rendering */}
      {effectiveType === "single" && (
        <QuizShell
          title={currentQuestion.title}
          subtitle={currentQuestion.subtitle || "Select one option to continue"}
          onBack={handleBack}
          backDisabled={isBackPending}
          isLoading={isLoading}
          error={error}
        >
          <RadioGroup label={currentQuestion.title} ariaLabelledBy="quiz-header-title">
            {currentQuestion.options?.map((opt) => (
              <OptionCard
                key={opt.code}
                label={opt.label}
                selected={singleValue === opt.code}
                selectionType="single"
                locked={isSubmitting || isBackPending}
                onClick={() => handleSingleOptionClick(opt.code)}
              />
            ))}
          </RadioGroup>
        </QuizShell>
      )}

      {/* Date Question Rendering */}
      {effectiveType === "date" && (
        <QuizShell
          title={currentQuestion.title}
          subtitle={currentQuestion.subtitle}
          onBack={handleBack}
          backDisabled={isBackPending}
          isLoading={isLoading}
          error={error}
          centerContent
          bottomAction={
            <QuizNextButton
              onClick={handleDateSubmit}
              disabled={
                !dateValue || isSubmitting || isLoading || isBackPending || wheelMoving
              }
              loading={isSubmitting}
              label="Next"
              ariaLabel="Confirm date and continue"
            />
          }
        >
          <WheelDatePicker
            value={dateValue}
            onChange={setDateValue}
            onMovingChange={setWheelMoving}
            disabled={isSubmitting || isLoading || isBackPending}
          />
        </QuizShell>
      )}

      {/* Multi Choice Question Rendering */}
      {effectiveType === "multi" && (
        <QuizShell
          title={currentQuestion.title}
          subtitle={currentQuestion.subtitle || "Select all that apply"}
          onBack={handleBack}
          backDisabled={isBackPending}
          isLoading={isLoading}
          error={error}
          bottomAction={
            <QuizNextButton
              onClick={handleMultiSubmit}
              disabled={multiValues.length === 0 || isSubmitting || isLoading || isBackPending}
              loading={isSubmitting}
              label={`Next (${multiValues.length})`}
              ariaLabel="Confirm choices and continue"
            />
          }
        >
          {currentQuestion.options?.map((opt) => (
            <OptionCard
              key={opt.code}
              label={opt.label}
              selected={multiValues.includes(opt.code)}
              selectionType="multi"
              locked={isSubmitting || isBackPending}
              onClick={() => {
                if (isSubmitting || isLoading || isBackPending) return;
                setMultiValues((prev) =>
                  prev.includes(opt.code)
                    ? prev.filter((c) => c !== opt.code)
                    : [...prev, opt.code]
                );
              }}
            />
          ))}
        </QuizShell>
      )}
    </div>
  );
}

export default function SoulmateQuizPage() {
  return (
    <Suspense fallback={<FlowShellFallback />}>
      <QuizPageContent />
    </Suspense>
  );
}
