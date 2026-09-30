"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type {
  QuizConfig,
  SavedAnswerDetail,
  SessionCurrentResponse,
} from "@/soulmate/api/session";
import { getFlowState } from "@/soulmate/api/session";
import {
  createStepPreparationStore,
  type PreparedStepEntry,
  type StepPreparationStore,
} from "./stepPreparation";

/**
 * Persistent shared flow state for the /soulmate funnel (DEV-SPEC §6 recovery;
 * batch 3 of `docs/UI-IMPROVEMENT-EXECUTION-PLAN.md`).
 *
 * Mounted once in the /soulmate layout, which stays alive across sibling route
 * navigations (quiz <-> transition screens <-> email). It expresses exactly the
 * three responsibilities the batch-3 plan assigns to shared state:
 *
 * 1. the current session and the session-pinned quiz config;
 * 2. the most recent SERVER-CONFIRMED step plus an immutable answers snapshot,
 *    together with a local operation sequence used only to discard stale async
 *    responses (never a server version or an authority);
 * 3. per-`sessionId+step` prepared flow metadata with pending/ready/error
 *    states and in-flight request reuse, so quiz->transition and
 *    transition->quiz hand-offs consume one prepared result instead of
 *    refetching on every mount.
 *
 * Everything lives in memory for the current page lifetime (no localStorage).
 * Answer updates are immutable; effects must depend on concrete session/step
 * values, never on the whole context object (see 223fc60).
 *
 * Without a provider (standalone/test rendering) the hook returns a no-op
 * default and every page falls back to its own bootstrap.
 */
export interface SharedFlowState {
  sessionId: string | null;
  sessionData: SessionCurrentResponse | null;
  quizConfig: QuizConfig | null;
  /** Last step the server confirmed via an answer/continue/back/flow response. */
  confirmedStep: string | null;
  setSession: (sessionId: string, sessionData: SessionCurrentResponse | null) => void;
  setQuizConfig: (config: QuizConfig) => void;
  /** Immutable answer snapshot update from a server-confirmed result (§6.2.1).
   *  Pass the `requestSessionId` the answer was submitted under; a confirmation
   *  from a superseded session is discarded (audit P1 fix). */
  confirmAnswer: (
    questionCode: string,
    saved: SavedAnswerDetail,
    confirmedStep?: string,
    requestSessionId?: string
  ) => void;
  /** Record a server-confirmed step; prunes preparations that no longer match (§6.2.4). */
  confirmStep: (step: string) => void;
  /** Bump the local operation sequence; returns the new value (§6.1, stale guard only). */
  bumpOp: () => number;
  /** Whether `seq` is still the latest local operation (stale-response discard). */
  isCurrentOp: (seq: number) => boolean;
  /** One flow-state request per session+target; ready/in-flight reused (§6.2.3). */
  ensurePrepared: (sessionId: string, step: string) => Promise<PreparedStepEntry>;
  getPrepared: (sessionId: string, step: string) => PreparedStepEntry | null;
}

const noopStore = createStepPreparationStore(() =>
  Promise.reject(new Error("no shared flow provider"))
);

const noopSharedFlow: SharedFlowState = {
  sessionId: null,
  sessionData: null,
  quizConfig: null,
  confirmedStep: null,
  setSession: () => undefined,
  setQuizConfig: () => undefined,
  confirmAnswer: () => undefined,
  confirmStep: () => undefined,
  bumpOp: () => 0,
  isCurrentOp: () => true,
  ensurePrepared: () =>
    Promise.resolve({
      status: "error" as const,
      sessionId: "",
      step: "",
      flowState: null,
      error: "no shared flow provider",
      promise: null,
    }),
  getPrepared: () => null,
};

const SharedFlowContext = createContext<SharedFlowState>(noopSharedFlow);

export function SharedFlowProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionCurrentResponse | null>(null);
  const [quizConfig, setQuizConfigState] = useState<QuizConfig | null>(null);
  const [confirmedStep, setConfirmedStep] = useState<string | null>(null);

  // Stable, render-independent instruments (never trigger re-renders themselves).
  const opSeqRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const storeRef = useRef<StepPreparationStore | null>(null);
  if (storeRef.current === null) {
    storeRef.current = createStepPreparationStore((sid) => getFlowState(sid));
  }
  const store = storeRef.current;

  const setSession = useCallback(
    (id: string, data: SessionCurrentResponse | null) => {
      setSessionId((prev) => {
        if (prev !== id) {
          // 6.2.4: a different session invalidates every prepared result, any
          // previously confirmed step, AND every in-flight operation — a stale
          // response from the old session must never land in the new one.
          store.clear();
          setConfirmedStep(null);
          opSeqRef.current += 1;
        }
        return id;
      });
      sessionIdRef.current = id;
      setSessionData(data);
    },
    [store]
  );

  const setQuizConfig = useCallback((config: QuizConfig) => setQuizConfigState(config), []);

  const confirmAnswer = useCallback(
    (questionCode: string, saved: SavedAnswerDetail, step?: string, requestSessionId?: string) => {
      // Audit P1 (batch 3): a confirmation from a superseded session must never
      // touch the current session's snapshot or confirmed step.
      if (requestSessionId !== undefined && requestSessionId !== sessionIdRef.current) {
        return;
      }
      setSessionData((prev) =>
        prev ? { ...prev, answers: { ...prev.answers, [questionCode]: saved } } : prev
      );
      if (step) {
        setConfirmedStep(step);
        // The confirmed next step supersedes any other in-memory preparation.
        store.invalidateExcept(step);
      }
    },
    [store]
  );

  const confirmStep = useCallback(
    (step: string) => {
      setConfirmedStep(step);
      store.invalidateExcept(step);
    },
    [store]
  );

  const bumpOp = useCallback(() => {
    opSeqRef.current += 1;
    return opSeqRef.current;
  }, []);

  const isCurrentOp = useCallback((seq: number) => seq === opSeqRef.current, []);

  const ensurePrepared = useCallback(
    (sid: string, step: string) => store.ensure(sid, step),
    [store]
  );
  const getPrepared = useCallback(
    (sid: string, step: string) => store.get(sid, step),
    [store]
  );

  const value = useMemo(
    () => ({
      sessionId,
      sessionData,
      quizConfig,
      confirmedStep,
      setSession,
      setQuizConfig,
      confirmAnswer,
      confirmStep,
      bumpOp,
      isCurrentOp,
      ensurePrepared,
      getPrepared,
    }),
    [
      sessionId,
      sessionData,
      quizConfig,
      confirmedStep,
      setSession,
      setQuizConfig,
      confirmAnswer,
      confirmStep,
      bumpOp,
      isCurrentOp,
      ensurePrepared,
      getPrepared,
    ]
  );

  return <SharedFlowContext.Provider value={value}>{children}</SharedFlowContext.Provider>;
}

export function useSharedFlow(): SharedFlowState {
  return useContext(SharedFlowContext);
}
