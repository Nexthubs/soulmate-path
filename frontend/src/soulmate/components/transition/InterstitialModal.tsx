"use client";

import React, { useEffect, useRef } from "react";

export type InterstitialType = "spiritual" | "psychic_artistry" | "warning";

/**
 * Sequential Transition-5 popup order per DEV-SPEC §5.7 & Figma:
 * spiritual (Popup-1, 102:425) -> psychic_artistry (Popup-2, 102:466) -> warning (Popup-3, 102:445) -> null (complete)
 */
export const INTERSTITIAL_POPUP_SEQUENCE: readonly InterstitialType[] = [
  "spiritual",
  "psychic_artistry",
  "warning",
] as const;

export function getNextInterstitialPopup(current: InterstitialType): InterstitialType | null {
  const idx = INTERSTITIAL_POPUP_SEQUENCE.indexOf(current);
  if (idx >= 0 && idx < INTERSTITIAL_POPUP_SEQUENCE.length - 1) {
    return INTERSTITIAL_POPUP_SEQUENCE[idx + 1];
  }
  return null;
}

export interface InterstitialModalProps {
  /**
   * Modal variant:
   * - "spiritual": Popup-1 (Figma 102:425)
   * - "psychic_artistry": Popup-2 (Figma 102:466)
   * - "warning": Popup-3 (Figma 102:445)
   */
  type: InterstitialType;

  /**
   * Whether the modal dialog is currently visible.
   */
  isOpen: boolean;

  /**
   * Callback fired when user selects "Yes" or "No".
   */
  onAnswer: (response: boolean) => void;

  /**
   * Optional custom title override.
   */
  customTitle?: string;

  /**
   * Optional custom description override.
   */
  customDescription?: string;

  /**
   * Optional dismiss/close handler. If omitted, calls onAnswer(false).
   */
  onDismiss?: () => void;

  /**
   * Non-blocking error message and optional retry callback.
   */
  error?: { message: string; onRetry?: () => void } | string | null;

  /**
   * Whether modal submit is in flight.
   */
  loading?: boolean;
}

const MODAL_CONTENT = {
  spiritual: {
    title: "Do you consider yourself a spiritual person?",
    description: null,
    isWarning: false,
  },
  psychic_artistry: {
    title: "Are you familiar with the concept of Psychic Artistry?",
    description: null,
    isWarning: false,
  },
  warning: {
    title: "WARNING",
    description:
      "We have noticed something shocking while searching for your Soulmate. Prepare for surprising results!",
    isWarning: true,
  },
};

/**
 * Accessible Interstitial Dialog Shell for Transition-5 Popups (Figma Nodes 102:425, 102:466, 102:445; DEV-SPEC §5.7).
 */
export function InterstitialModal({
  type,
  isOpen,
  onAnswer,
  customTitle,
  customDescription,
  onDismiss,
  error = null,
  loading = false,
}: InterstitialModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const initialFocusRef = useRef<HTMLButtonElement>(null);

  const errorMessage = typeof error === "string" ? error : error?.message;
  const onRetry = typeof error === "object" && error !== null ? error.onRetry : undefined;

  const content = MODAL_CONTENT[type];
  const title = customTitle || content.title;
  const description = customDescription || content.description;

  // Handle keyboard Escape and focus trap
  useEffect(() => {
    if (!isOpen) return;

    // Focus the first button on mount
    initialFocusRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (onDismiss) {
          onDismiss();
        } else {
          onAnswer(false);
        }
      } else if (e.key === "Tab") {
        if (!dialogRef.current) return;
        const focusableElements = dialogRef.current.querySelectorAll<HTMLButtonElement>("button:not([disabled])");
        if (focusableElements.length === 0) return;
        const first = focusableElements[0];
        const last = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onAnswer, onDismiss]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-200"
      data-testid={`interstitial-modal-${type}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          if (onDismiss) onDismiss();
          else onAnswer(false);
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="interstitial-title"
        aria-describedby={description ? "interstitial-desc" : undefined}
        className="w-full max-w-[342px] bg-white rounded-[28px] p-7 shadow-2xl flex flex-col items-center text-center space-y-6 animate-in zoom-in-95 duration-200"
      >
        {/* Top Icon / Header Indicator */}
        {content.isWarning ? (
          <div className="pt-2">
            <span
              id="interstitial-title"
              className="font-sans font-extrabold text-[24px] tracking-wider text-[#eab308] uppercase"
            >
              {title}
            </span>
          </div>
        ) : (
          <div className="flex flex-col items-center pt-2 space-y-4">
            {/* Sparkle Vector Icon */}
            <div className="w-10 h-10 flex items-center justify-center text-[#eab308]" aria-hidden="true">
              <svg className="w-9 h-9 fill-current" viewBox="0 0 24 24">
                <path d="M12 0l2.5 8.5 8.5 2.5-8.5 2.5-2.5 8.5-2.5-8.5-8.5-2.5 8.5-2.5z" />
              </svg>
            </div>
            <h3
              id="interstitial-title"
              className="font-sans font-semibold text-[18px] leading-[26px] text-[#111827] px-2"
            >
              {title}
            </h3>
          </div>
        )}

        {/* Warning Description */}
        {description && (
          <p
            id="interstitial-desc"
            className="font-sans text-[14px] leading-[22px] text-[#374151] px-1"
          >
            {description}
          </p>
        )}

        {/* Action Buttons: No / Yes */}
        {errorMessage && (
          <div
            role="alert"
            data-testid="interstitial-error-banner"
            className="w-full p-2.5 rounded-xl bg-red-50/90 border border-red-200/80 text-red-700 text-xs flex items-center justify-between shadow-xs"
          >
            <div className="flex items-center gap-1.5 text-left">
              <svg
                className="w-3.5 h-3.5 text-red-500 shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <span>{errorMessage}</span>
            </div>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="font-medium underline hover:text-red-900 cursor-pointer ml-1.5 shrink-0"
              >
                Retry
              </button>
            )}
          </div>
        )}

        <div className="w-full flex items-center gap-3 pt-2">
          <button
            ref={initialFocusRef}
            type="button"
            onClick={() => onAnswer(false)}
            disabled={loading}
            className="flex-1 h-[52px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[16px] transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label="No"
          >
            No
          </button>
          <button
            type="button"
            onClick={() => onAnswer(true)}
            disabled={loading}
            className="flex-1 h-[52px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[16px] transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            aria-label="Yes"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Saving...</span>
              </>
            ) : (
              "Yes"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Dedicated Warning Modal (Popup-3, Figma Node 102:445).
 * Convenient wrapper around InterstitialModal with type="warning".
 */
export function WarningModal(
  props: Omit<InterstitialModalProps, "type">
) {
  return <InterstitialModal {...props} type="warning" />;
}
