"use client";

import React, { useEffect, useRef } from "react";

export type InterstitialType = "spiritual" | "psychic_artistry" | "warning";

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
}: InterstitialModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const initialFocusRef = useRef<HTMLButtonElement>(null);

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
        <div className="w-full flex items-center gap-3 pt-2">
          <button
            ref={initialFocusRef}
            type="button"
            onClick={() => onAnswer(false)}
            className="flex-1 h-[52px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[16px] transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer"
            aria-label="No"
          >
            No
          </button>
          <button
            type="button"
            onClick={() => onAnswer(true)}
            className="flex-1 h-[52px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[16px] transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer"
            aria-label="Yes"
          >
            Yes
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
