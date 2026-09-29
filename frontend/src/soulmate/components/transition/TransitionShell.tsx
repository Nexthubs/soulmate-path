"use client";

import React from "react";

export interface TransitionShellProps {
  /**
   * Transition step number (0 through 5).
   */
  step: number;

  /**
   * Main transition title / heading.
   */
  title?: React.ReactNode;

  /**
   * Subtitle, explanatory text, or dynamic copy slot.
   */
  subtitle?: React.ReactNode;

  /**
   * Top or central illustration / badge node.
   */
  illustration?: React.ReactNode;

  /**
   * Optional status badge (e.g. "Sketching now" in Transition-1).
   */
  badge?: React.ReactNode;

  /**
   * Additional body content (e.g. testimonials in Transition-0 or progress bars in Transition-5).
   */
  children?: React.ReactNode;

  /**
   * Callback fired when user clicks the primary Continue CTA.
   */
  onContinue: () => void;

  /**
   * Button label. Defaults to "Continue".
   */
  continueLabel?: string;

  /**
   * Whether the continue button is in loading or disabled state.
   */
  loading?: boolean;

  /**
   * Disables Continue (without a spinner) until the session and the server
   * step validation for this screen have completed — the server must advance
   * the flow before any navigation.
   */
  continueDisabled?: boolean;

  /**
   * Non-blocking error message and optional retry callback.
   */
  error?: { message: string; onRetry?: () => void } | string | null;

  /**
   * Optional extra container class name.
   */
  className?: string;
}

/**
 * Shared Transition Layout Shell for steps 0 to 5 (Figma Nodes 102:245, 102:304, 102:320, 102:345, 102:372, 102:386).
 * Follows the 390px mobile baseline and warm pastel gradient background.
 */
export function TransitionShell({
  step,
  title,
  subtitle,
  illustration,
  badge,
  children,
  onContinue,
  continueLabel = "Continue",
  loading = false,
  continueDisabled = false,
  error = null,
  className = "",
}: TransitionShellProps) {
  const errorMessage = typeof error === "string" ? error : error?.message;
  const onRetry = typeof error === "object" && error !== null ? error.onRetry : undefined;
  return (
    <div
      data-testid={`transition-shell-step-${step}`}
      className={`flex flex-col min-h-screen justify-between items-center w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900 px-6 py-8 overflow-x-hidden ${className}`}
    >
      {/* Top Spacer / Status Header */}
      <div className="w-full flex flex-col items-center pt-4">
        {badge && (
          <div className="mb-4" data-testid="transition-badge">
            {badge}
          </div>
        )}
      </div>

      {/* Center Content Slot */}
      <main className="flex-1 flex flex-col items-center justify-center text-center w-full my-auto max-w-[342px] space-y-5">
        {illustration && (
          <div className="my-2 flex justify-center items-center" data-testid="transition-illustration">
            {illustration}
          </div>
        )}

        {title && (
          <h2 className="font-sans font-semibold text-[24px] leading-[32px] tracking-tight text-[#111827]">
            {title}
          </h2>
        )}

        {subtitle && (
          <div className="font-sans text-[15px] leading-[23px] text-[#4b5563] max-w-[312px]">
            {subtitle}
          </div>
        )}

        {children && <div className="w-full mt-3">{children}</div>}
      </main>

      {/* Bottom Action Area */}
      <footer className="w-full max-w-[348px] pt-4 pb-2">
        {/* Error Banner with In-Place Retry (DEV-SPEC §4.2) */}
        {errorMessage && (
          <div
            role="alert"
            data-testid="transition-error-banner"
            className="w-full mb-3 p-3.5 rounded-xl bg-red-50/90 border border-red-200/80 text-red-700 text-xs flex items-center justify-between shadow-xs"
          >
            <div className="flex items-center gap-2">
              <svg
                className="w-4 h-4 text-red-500 shrink-0"
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
                className="font-medium underline hover:text-red-900 cursor-pointer ml-2 shrink-0"
              >
                Retry
              </button>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={onContinue}
          disabled={loading || continueDisabled}
          className="w-full h-[54px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[17px] leading-[25.5px] tracking-[0.425px] shadow-md transition-all flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={continueLabel}
        >
          {loading ? (
            <span className="inline-flex items-center gap-2">
              <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Loading...</span>
            </span>
          ) : (
            continueLabel
          )}
        </button>
      </footer>
    </div>
  );
}
