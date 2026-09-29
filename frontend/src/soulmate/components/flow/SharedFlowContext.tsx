"use client";

import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import type {
  QuizConfig,
  SessionCurrentResponse,
} from "@/soulmate/api/session";

/**
 * Persistent shared flow state for the /soulmate funnel (DEV-SPEC §6 recovery).
 *
 * Mounted once in the /soulmate layout, which stays alive across sibling route
 * navigations (quiz <-> transition screens <-> email). Pages that obtain the
 * session or the session-pinned quiz config store them here so the next page
 * hydrates locally instead of re-running a full bootstrap on every mount (the
 * second visual hop after route changes).
 *
 * Deliberately holds NO mutable-per-page data (e.g. flow state): effects that
 * write back a value they also read from the context re-trigger themselves on
 * every context identity change. Flow state is fetched fresh by each page that
 * needs it.
 *
 * Without a provider (standalone/test rendering) the hook returns a no-op
 * default and every page falls back to its own bootstrap.
 */
export interface SharedFlowState {
  sessionId: string | null;
  sessionData: SessionCurrentResponse | null;
  quizConfig: QuizConfig | null;
  setSession: (sessionId: string, sessionData: SessionCurrentResponse | null) => void;
  setQuizConfig: (config: QuizConfig) => void;
}

const noopSharedFlow: SharedFlowState = {
  sessionId: null,
  sessionData: null,
  quizConfig: null,
  setSession: () => undefined,
  setQuizConfig: () => undefined,
};

const SharedFlowContext = createContext<SharedFlowState>(noopSharedFlow);

export function SharedFlowProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionCurrentResponse | null>(null);
  const [quizConfig, setQuizConfigState] = useState<QuizConfig | null>(null);

  const setSession = useCallback((id: string, data: SessionCurrentResponse | null) => {
    setSessionId(id);
    setSessionData(data);
  }, []);
  const setQuizConfig = useCallback((config: QuizConfig) => setQuizConfigState(config), []);

  const value = useMemo(
    () => ({
      sessionId,
      sessionData,
      quizConfig,
      setSession,
      setQuizConfig,
    }),
    [sessionId, sessionData, quizConfig, setSession, setQuizConfig]
  );

  return <SharedFlowContext.Provider value={value}>{children}</SharedFlowContext.Provider>;
}

export function useSharedFlow(): SharedFlowState {
  return useContext(SharedFlowContext);
}
