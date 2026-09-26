"use client";

import React, { useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  ArtifactItemState,
  ArtifactType,
  CombinedUIState,
  calculateServerClockOffsetMs,
  evaluateCountdownZeroNotification,
  getCalibratedRemainingSeconds,
  deriveCombinedUIState,
  formatCountdown,
} from "./types";

export interface ResultItemCardProps {
  /**
   * Type of artifact card: "sketch" or "report".
   */
  type: ArtifactType;

  /**
   * Authoritative item state from Result API (DEV-SPEC §10).
   */
  state: ArtifactItemState;

  /**
   * Authoritative server time in ISO 8601 string format (TIME-01).
   */
  serverTime?: string;

  /**
   * Client-to-server clock offset in milliseconds captured at the last fetch (SP-504, TIME-01).
   * When provided it takes precedence over `serverTime` for countdown calibration.
   */
  clockOffsetMs?: number | null;

  /**
   * Custom title override.
   */
  titleOverride?: string;

  /**
   * Callback fired when user clicks the primary action button (e.g. "Check Now", "View Sketch").
   */
  onAction?: (type: ArtifactType) => void;

  /**
   * Callback fired when user clicks "Retry" on failed state.
   */
  onRetry?: (type: ArtifactType) => void;

  /**
   * Callback fired once per `unlock_at` when the calibrated countdown reaches zero while the
   * server still reports LOCKED. The parent must refetch server state; the server response —
   * never the local zero — decides whether content unlocks (SP-504, TIME-01).
   */
  onCountdownZero?: (type: ArtifactType) => void;

  /**
   * Additional container CSS classes.
   */
  className?: string;
}

const DEFAULT_TITLES: Record<ArtifactType, string> = {
  sketch: "Hint’s Astrologer is drawing a portrait of your soulmate",
  report: "Your Soulmate Report",
};

const SUB_BADGES: Record<ArtifactType, string> = {
  sketch: "✦ HAND-CRAFTING ✦",
  report: "✦ ANALYZING CHART ✦",
};

/**
 * Fixture-driven card component for Result items (Figma Nodes 102:1201, 102:1332; DEV-SPEC §10).
 * Decouples availability from generation state and renders:
 * - countdown (locked)
 * - ready (unlocked, not started)
 * - generating (unlocked, queued/processing)
 * - completed (unlocked, completed)
 * - failed (unlocked, failed)
 */
export function ResultItemCard({
  type,
  state,
  serverTime = new Date().toISOString(),
  clockOffsetMs,
  titleOverride,
  onAction,
  onRetry,
  onCountdownZero,
  className = "",
}: ResultItemCardProps) {
  const uiState: CombinedUIState = deriveCombinedUIState(state);
  const cardTitle = titleOverride || DEFAULT_TITLES[type];
  const subBadge = SUB_BADGES[type];

  // Countdown calibration (TIME-01, SP-504): anchored to server time via the clock offset
  // captured at the last fetch; a wrong client clock cannot change the countdown.
  const effectiveOffsetMs: number =
    typeof clockOffsetMs === "number" && Number.isFinite(clockOffsetMs)
      ? clockOffsetMs
      : calculateServerClockOffsetMs(serverTime);
  const initialSeconds = getCalibratedRemainingSeconds(state.unlock_at, effectiveOffsetMs);
  const [remainingSeconds, setRemainingSeconds] = useState(initialSeconds);

  // Every refetch brings a fresh server_time: recalibrate from absolute timestamps (SP-504).
  useEffect(() => {
    setRemainingSeconds(getCalibratedRemainingSeconds(state.unlock_at, effectiveOffsetMs));
  }, [state.unlock_at, effectiveOffsetMs]);

  // Local tick for smooth countdown display only — pure interpolation between server calibrations.
  useEffect(() => {
    if (uiState !== "countdown" || remainingSeconds <= 0) return;

    const timer = setInterval(() => {
      setRemainingSeconds((prev) => Math.max(0, prev - 1));
    }, 1000);

    return () => clearInterval(timer);
  }, [uiState, remainingSeconds]);

  // Reaching zero while still LOCKED triggers a server refetch — never a local unlock (SP-504).
  const zeroNotifiedUnlockRef = useRef<string | null>(null);
  const zeroDecision = evaluateCountdownZeroNotification(
    uiState,
    remainingSeconds,
    state.unlock_at,
    zeroNotifiedUnlockRef.current
  );
  useEffect(() => {
    if (zeroDecision.nextLastNotifiedUnlock !== zeroNotifiedUnlockRef.current) {
      zeroNotifiedUnlockRef.current = zeroDecision.nextLastNotifiedUnlock;
    }
    if (zeroDecision.notify) {
      onCountdownZero?.(type);
    }
  }, [zeroDecision.notify, zeroDecision.nextLastNotifiedUnlock, onCountdownZero, type]);

  return (
    <div
      data-testid={`result-card-${type}`}
      data-ui-state={uiState}
      data-availability={state.availability}
      data-generation={state.generation}
      className={`w-full rounded-3xl p-6 bg-white border border-neutral-100 shadow-sm transition-all duration-300 flex flex-col items-center text-center ${className}`}
    >
      {/* 1. COUNTDOWN STATE (LOCKED, Figma 102:1201) */}
      {uiState === "countdown" && (
        <div className="w-full flex flex-col items-center space-y-4" data-testid="card-state-countdown">
          <h3 className="font-sans font-bold text-[18px] leading-[24px] text-neutral-900 max-w-[280px]">
            {cardTitle}
          </h3>

          {/* Segmented Ring Graphic */}
          <div className="relative w-44 h-44 flex items-center justify-center my-2">
            {/* SVG segmented circular arcs matching Figma 102:1201 */}
            <svg className="w-full h-full transform -rotate-45" viewBox="0 0 100 100">
              {/* Segment 1 */}
              <circle
                cx="50"
                cy="50"
                r="40"
                fill="none"
                stroke="#7c3aed"
                strokeWidth="7"
                strokeDasharray="45 15"
                strokeLinecap="round"
                className="opacity-90"
              />
              {/* Segment 2 */}
              <circle
                cx="50"
                cy="50"
                r="40"
                fill="none"
                stroke="#a78bfa"
                strokeWidth="7"
                strokeDasharray="25 35"
                strokeDashoffset="70"
                strokeLinecap="round"
                className="opacity-70"
              />
            </svg>

            {/* Inner Content */}
            <div className="absolute inset-0 flex flex-col items-center justify-center space-y-1">
              <span className="text-[11px] font-medium text-neutral-400 tracking-wider">
                预计完成：
              </span>
              <span
                data-testid="countdown-timer"
                className="font-sans font-black text-[22px] tracking-tight text-[#5b2f91]"
              >
                {formatCountdown(remainingSeconds)}
              </span>
              <span className="text-[10px] font-extrabold text-[#7c3aed] tracking-wider uppercase">
                {subBadge}
              </span>
            </div>
          </div>

          <p className="text-xs text-neutral-400">
            Locked until server unlock time. Client timer is display-only.
          </p>
        </div>
      )}

      {/* 2. READY STATE (UNLOCKED + NOT_STARTED, Figma 102:1332) */}
      {uiState === "ready" && (
        <div className="w-full flex flex-col space-y-4" data-testid="card-state-ready">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-3">
              {/* Glowing star badge */}
              <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-rose-400 to-amber-300 flex items-center justify-center text-white shadow-md">
                <svg className="w-6 h-6 fill-current" viewBox="0 0 24 24">
                  <path d="M12 1.5l2.8 6.6 7.2.6-5.4 4.8 1.6 7-6.2-3.8-6.2 3.8 1.6-7-5.4-4.8 7.2-.6z" />
                </svg>
              </div>
              <div className="text-left">
                <h3 className="font-sans font-bold text-[18px] leading-[24px] text-neutral-900">
                  {cardTitle}
                </h3>
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <span
                data-testid="badge-ready"
                className="px-2.5 py-1 rounded-full bg-rose-50 border border-rose-200 text-rose-600 font-bold text-xs tracking-wider"
              >
                READY!
              </span>
              <span className="text-rose-500 font-bold text-lg">›</span>
            </div>
          </div>

          <button
            type="button"
            data-testid="ready-action-button"
            onClick={() => onAction && onAction(type)}
            className="w-full h-[52px] rounded-2xl bg-gradient-to-r from-[#ff6b6b] to-[#ff4b4b] hover:from-[#ff5b5b] hover:to-[#ff3b3b] active:scale-[0.99] text-white font-sans font-bold text-[16px] shadow-lg shadow-rose-200 transition-all flex items-center justify-center gap-2 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
          >
            <span>Check Now</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      )}

      {/* 3. GENERATING STATE (UNLOCKED + QUEUED/PROCESSING) */}
      {uiState === "generating" && (
        <div
          className="w-full flex flex-col items-center space-y-4 py-2"
          data-testid="card-state-generating"
          aria-busy="true"
        >
          <div className="w-14 h-14 rounded-full bg-purple-50 border-2 border-purple-200 flex items-center justify-center text-purple-600 animate-pulse">
            <svg className="w-7 h-7 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          </div>

          <div className="space-y-1">
            <h3 className="font-sans font-bold text-[18px] text-neutral-900">
              {type === "sketch"
                ? "Drawing Your Soulmate Portrait..."
                : "Compiling Your Personal Report..."}
            </h3>
            <p className="text-xs text-neutral-500 max-w-[260px] mx-auto">
              {state.generation === "QUEUED"
                ? "Your request is in the generation queue."
                : "Astrological portrait generation in progress. Usually takes under 2 minutes."}
            </p>
          </div>

          <div className="w-full bg-neutral-100 rounded-full h-2 overflow-hidden mt-2">
            <div className="bg-gradient-to-r from-purple-500 to-indigo-600 h-full w-2/3 rounded-full animate-pulse" />
          </div>
        </div>
      )}

      {/* 4. COMPLETED STATE (UNLOCKED + COMPLETED) */}
      {uiState === "completed" && (
        <div className="w-full flex flex-col items-center space-y-4" data-testid="card-state-completed">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-3 text-left">
              <div className="w-12 h-12 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600 shadow-xs">
                <svg className="w-6 h-6 fill-current" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <div>
                <h3 className="font-sans font-bold text-[17px] text-neutral-900 leading-tight">
                  {type === "sketch" ? "Your Portrait is Ready!" : "Your Report is Ready!"}
                </h3>
                <span className="text-xs text-emerald-600 font-semibold">Completed</span>
              </div>
            </div>

            {state.artifact_url && (
              <div className="w-11 h-11 rounded-lg overflow-hidden border border-neutral-200 relative shrink-0">
                <Image
                  src={state.artifact_url}
                  alt="Completed artifact thumbnail"
                  fill
                  className="object-cover"
                  unoptimized
                />
              </div>
            )}
          </div>

          <button
            type="button"
            data-testid="completed-action-button"
            onClick={() => onAction && onAction(type)}
            className="w-full h-[50px] rounded-2xl bg-neutral-900 hover:bg-neutral-800 text-white font-sans font-semibold text-[15px] transition-all flex items-center justify-center gap-2 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-700"
          >
            <span>{type === "sketch" ? "View Soulmate Sketch" : "Read Full Report"}</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      )}

      {/* 5. FAILED STATE (UNLOCKED + FAILED) */}
      {uiState === "failed" && (
        <div
          className="w-full flex flex-col items-center space-y-3 py-1"
          data-testid="card-state-failed"
          role="alert"
        >
          <div className="w-12 h-12 rounded-full bg-red-50 border border-red-200 flex items-center justify-center text-red-600">
            <svg className="w-6 h-6 fill-current" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clipRule="evenodd"
              />
            </svg>
          </div>

          <div className="space-y-1">
            <h3 className="font-sans font-bold text-[17px] text-red-900">Generation Interrupted</h3>
            <p className="text-xs text-red-600 max-w-[260px] mx-auto">
              {state.error_message || "We encountered an issue creating your artifact. Please try again."}
            </p>
          </div>

          <div className="w-full flex items-center gap-2 pt-1">
            <button
              type="button"
              data-testid="retry-action-button"
              onClick={() => onRetry && onRetry(type)}
              className="flex-1 h-[46px] rounded-xl bg-red-600 hover:bg-red-700 text-white font-sans font-semibold text-[14px] transition-colors cursor-pointer"
            >
              Retry
            </button>
            <a
              href="#support"
              className="flex-1 h-[46px] rounded-xl bg-neutral-100 hover:bg-neutral-200 text-neutral-700 font-sans font-medium text-[14px] flex items-center justify-center transition-colors"
            >
              Support
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
