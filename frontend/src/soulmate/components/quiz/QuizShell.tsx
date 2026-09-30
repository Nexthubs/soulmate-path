"use client";

import React from "react";
import { useRouter } from "next/navigation";

export interface QuizShellProps {
  /**
   * Main question title (e.g. "Select your gender" or "In this relationship...").
   */
  title: React.ReactNode;

  /**
   * Optional subtitle or descriptive helper (e.g. Q08 date helper text).
   */
  subtitle?: React.ReactNode;

  /**
   * Whether to display the top back button. Defaults to true.
   */
  showBack?: boolean;

  /**
   * Custom back action. If omitted, uses Next.js router.back().
   */
  onBack?: () => void;

  /**
   * Main interactive content (Option cards, Date picker, Multi-select list, etc.).
   */
  children: React.ReactNode;

  /**
   * Optional bottom action area (e.g. "Next" button for multi-choice or date submission).
   */
  bottomAction?: React.ReactNode;

  /**
   * In-place loading state during step transitions or async operations.
   */
  isLoading?: boolean;

  /**
   * Disables the back button while an in-flight back navigation resolves,
   * WITHOUT swapping the rendered question for a skeleton.
   */
  backDisabled?: boolean;

  /**
   * Non-blocking error message and optional retry callback (DEV-SPEC §4.2).
   */
  error?: { message: string; onRetry?: () => void } | string | null;

  /**
   * Optional extra container styling.
   */
  className?: string;
}

/**
 * Shared Quiz Layout Shell (Figma Nodes 102:121, 102:201; DEV-SPEC §2.1, §4.2–4.4, §16).
 * Enforces unified visual hierarchy, back navigation, responsive slot, and error handling
 * across all question types without duplicating page boilerplate.
 */
export function QuizShell({
  title,
  subtitle,
  showBack = true,
  onBack,
  backDisabled = false,
  children,
  bottomAction,
  isLoading = false,
  error = null,
  className = "",
}: QuizShellProps) {
  const router = useRouter();

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      router.back();
    }
  };

  const errorMessage = typeof error === "string" ? error : error?.message;
  const onRetry = typeof error === "object" ? error?.onRetry : undefined;

  return (
    // Full-width warm background layer (batch 1); the centered max-390px slot
    // below keeps the 390px geometry identical while the gradient covers the
    // whole viewport on wider screens.
    <div
      className={`flex flex-col w-full sp-fill-vh bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900 overflow-x-hidden ${className}`}
    >
      <div className="w-full max-w-[390px] mx-auto flex flex-col flex-1 justify-between items-center">
        {/* Top Header / Back Navigation (Figma Nodes 102:124, 102:204) */}
        <header className="w-full flex items-center justify-between px-6 pt-[calc(1.5rem+var(--sp-safe-top))] pb-2 min-h-[58px]">
          {showBack ? (
            <button
              type="button"
              onClick={handleBack}
              disabled={backDisabled}
              className="flex items-center justify-center w-9 h-9 rounded-full bg-white/60 hover:bg-white text-neutral-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 shadow-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-white/60"
              aria-label="Go back to previous step"
              data-testid="quiz-back-button"
            >
              {/* SVG Chevron Left */}
              <svg
                className="w-5 h-5 text-neutral-900"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2.2}
                  d="M15 19l-7-7 7-7"
                />
              </svg>
            </button>
          ) : (
            <div className="w-9 h-9" aria-hidden="true" />
          )}

          {/* Brand indicator / spacer */}
          <span className="font-serif text-lg tracking-wide text-neutral-400 select-none">
            Hint
          </span>
          <div className="w-9 h-9" aria-hidden="true" />
        </header>

        {/* Main Content Area */}
        <main
          className={`flex-1 flex flex-col items-center w-full px-6 pt-2 ${
            bottomAction ? "pb-6" : "pb-[calc(1.5rem+var(--sp-safe-bottom))]"
          }`}
        >
          {/* Question Header (Figma Nodes 102:127, 102:207) */}
          <div className="w-full text-center max-w-[342px] mt-2 mb-6">
            <h2 className="font-sans font-semibold text-[20px] leading-[30px] tracking-[0.6px] text-[#241a4a]">
              {title}
            </h2>
            {subtitle && (
              <p className="font-sans text-[13px] leading-[20px] text-[#6b7280] mt-2">
                {subtitle}
              </p>
            )}
          </div>

          {/* Error Banner with In-Place Retry (DEV-SPEC §4.2) */}
          {errorMessage && (
            <div
              role="alert"
              data-testid="quiz-error-banner"
              className="w-full max-w-[342px] mb-4 p-3.5 rounded-xl bg-red-50/90 border border-red-200/80 text-red-700 text-xs flex items-center justify-between shadow-xs"
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

          {/* Loading State or Interactive Slot */}
          {isLoading ? (
            <div
              data-testid="quiz-loading-skeleton"
              className="w-full max-w-[342px] flex flex-col gap-3.5 my-auto py-8 animate-pulse"
              aria-busy="true"
              aria-label="Loading question content"
            >
              <div className="h-16 bg-white/70 rounded-2xl w-full" />
              <div className="h-16 bg-white/70 rounded-2xl w-full" />
              <div className="h-16 bg-white/70 rounded-2xl w-full" />
              <div className="h-16 bg-white/70 rounded-2xl w-full" />
            </div>
          ) : (
            <div className="w-full max-w-[342px] flex flex-col gap-3.5">
              {children}
            </div>
          )}
        </main>

        {/* Optional Bottom Action Area (Figma Node 102:241) */}
        {bottomAction && (
          <footer className="w-full max-w-[342px] px-6 pt-2 pb-[calc(2.5rem+var(--sp-safe-bottom))] flex flex-col items-center">
            {bottomAction}
          </footer>
        )}
      </div>
    </div>
  );
}

/**
 * Reusable Bottom Next Button component matching Figma Node 102:242
 */
export interface QuizNextButtonProps {
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  label?: string;
  ariaLabel?: string;
}

export function QuizNextButton({
  onClick,
  disabled = false,
  loading = false,
  label = "Next",
  ariaLabel = "Proceed to next step",
}: QuizNextButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`w-full h-[60px] rounded-[20px] font-sans font-medium text-[20px] leading-[28px] text-white transition-all shadow-md flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 ${
        disabled || loading
          ? "bg-[#2c2c2e]/40 text-neutral-300 cursor-not-allowed shadow-none"
          : "bg-[#2c2c2e] hover:bg-[#1f1f21] active:bg-black cursor-pointer hover:shadow-lg"
      }`}
      aria-label={ariaLabel}
      aria-disabled={disabled || loading}
    >
      {loading ? (
        <span className="inline-flex items-center gap-2">
          <svg
            className="animate-spin h-5 w-5 text-white"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            />
          </svg>
          <span>Saving...</span>
        </span>
      ) : (
        label
      )}
    </button>
  );
}
