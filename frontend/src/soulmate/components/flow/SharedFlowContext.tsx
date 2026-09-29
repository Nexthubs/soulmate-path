"use client";

import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import type {
  FlowStateResponse,
  QuizConfig,
  SessionCurrentResponse,
} from "@/soulmate/api/session";

/**
 * Persistent shared flow state for the /soulmate funnel (DEV-SPEC §6 recovery).
 *
 * Mounted once in the /soulmate layout, which stays alive across sibling route
 * navigations (quiz <-> transition screens <-> email). Pages that obtain the
 * session, the session-pinned quiz config, or flow state store them here so
 * the next page hydrates locally instead of re-running a full bootstrap on
 * every mount (the second visual hop after route changes).
 *
 * Without a provider (standalone/test rendering) the hook returns a no-op
 * default and every page falls back to its own bootstrap.
 */
export interface SharedFlowState {
  sessionId: string | null;
  sessionData: SessionCurrentResponse | null;
  quizConfig: QuizConfig | null;
  flowState: FlowStateResponse | null;
  setSession: (sessionId: string, sessionData: SessionCurrentResponse | null) => void;
  setQuizConfig: (config: QuizConfig) => void;
  setFlowState: (state: FlowStateResponse | null) => void;
}

const noopSharedFlow: SharedFlowState = {
  sessionId: null,
  sessionData: null,
  quizConfig: null,
  flowState: null,
  setSession: () => undefined,
  setQuizConfig: () => undefined,
  setFlowState: () => undefined,
};

const SharedFlowContext = createContext<SharedFlowState>(noopSharedFlow);

export function SharedFlowProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionCurrentResponse | null>(null);
  const [quizConfig, setQuizConfigState] = useState<QuizConfig | null>(null);
  const [flowState, setFlowStateState] = useState<FlowStateResponse | null>(null);

  const setSession = useCallback((id: string, data: SessionCurrentResponse | null) => {
    setSessionId(id);
    setSessionData(data);
  }, []);
  const setQuizConfig = useCallback((config: QuizConfig) => setQuizConfigState(config), []);
  const setFlowState = useCallback(
    (state: FlowStateResponse | null) => setFlowStateState(state),
    []
  );

  const value = useMemo(
    () => ({
      sessionId,
      sessionData,
      quizConfig,
      flowState,
      setSession,
      setQuizConfig,
      setFlowState,
    }),
    [sessionId, sessionData, quizConfig, flowState, setSession, setQuizConfig, setFlowState]
  );

  return <SharedFlowContext.Provider value={value}>{children}</SharedFlowContext.Provider>;
}

export function useSharedFlow(): SharedFlowState {
  return useContext(SharedFlowContext);
}
