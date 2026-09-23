"use client";

import React from "react";

export interface OptionCardProps {
  /**
   * Option display label (can include text or rich content).
   */
  label: React.ReactNode;

  /**
   * Whether this option is currently selected.
   */
  selected: boolean;

  /**
   * Callback fired when option is clicked or triggered via keyboard.
   */
  onClick: () => void;

  /**
   * Selection type determining ARIA semantics (radio for single-choice, checkbox for multi-choice).
   * Defaults to "single".
   */
  selectionType?: "single" | "multi";

  /**
   * Whether the option card is disabled (e.g. during answer submission per DEV-SPEC §4.2).
   */
  disabled?: boolean;

  /**
   * Error state indicator (e.g. when field has a validation error).
   */
  hasError?: boolean;

  /**
   * Optional custom test ID.
   */
  testId?: string;

  /**
   * Optional custom accessible name.
   */
  ariaLabel?: string;

  /**
   * Optional extra container CSS class names.
   */
  className?: string;
}

/**
 * OptionCard component (Figma Nodes 102:130, 102:137; DEV-SPEC §2.1, §4.2–4.3).
 * Shared visual primitive for both single-select and multi-select questions.
 */
export function OptionCard({
  label,
  selected,
  onClick,
  selectionType = "single",
  disabled = false,
  hasError = false,
  testId,
  ariaLabel,
  className = "",
}: OptionCardProps) {
  const role = selectionType === "single" ? "radio" : "checkbox";

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      onClick();
    }
  };

  // Base card styles conforming to Figma 342px mobile card spec
  let stateClasses = "bg-white/60 hover:bg-white/90 border-2 border-transparent shadow-xs text-[#1f2937]";

  if (hasError) {
    stateClasses = "border-2 border-red-400 bg-red-50/70 shadow-xs text-red-900";
  } else if (selected) {
    stateClasses = "bg-white/80 border-2 border-[#5c3c4f] shadow-xs text-[#111827]";
  }

  if (disabled) {
    stateClasses = "opacity-50 cursor-not-allowed pointer-events-none bg-white/40 border-2 border-transparent";
  }

  return (
    <div
      role={role}
      tabIndex={disabled ? -1 : 0}
      aria-checked={selected}
      aria-disabled={disabled}
      aria-label={ariaLabel}
      data-testid={testId || `option-card-${selectionType}`}
      onClick={disabled ? undefined : onClick}
      onKeyDown={handleKeyDown}
      className={`w-full min-h-[68px] p-5 rounded-2xl flex items-center justify-between text-left transition-all duration-150 select-none cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 ${stateClasses} ${className}`}
    >
      {/* Label Content */}
      <div className="font-sans font-medium text-[15px] leading-[25.5px] tracking-[0.425px] flex-1 pr-3">
        {label}
      </div>

      {/* Circle Indicator (Figma Nodes 102:133, 102:140) */}
      <div
        data-testid="option-indicator"
        className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 transition-colors duration-150 ${
          selected
            ? "bg-[#5c3c4f] border-2 border-[#5c3c4f]"
            : "border-2 border-neutral-300 bg-transparent"
        }`}
        aria-hidden="true"
      >
        {selected && (
          <svg
            data-testid="option-checkmark"
            className="w-3.5 h-3.5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2.6}
              d="M5 13l4 4L19 7"
            />
          </svg>
        )}
      </div>
    </div>
  );
}
