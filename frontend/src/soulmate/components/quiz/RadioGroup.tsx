"use client";

import React, { useRef } from "react";

export interface RadioGroupProps {
  /**
   * Accessible name for the radio group (e.g. question title).
   */
  label?: string;

  /**
   * ID of the element that labels this radio group.
   */
  ariaLabelledBy?: string;

  /**
   * Radio items / OptionCards.
   */
  children: React.ReactNode;

  /**
   * Custom CSS classes.
   */
  className?: string;

  /**
   * Test identifier.
   */
  testId?: string;
}

/**
 * Accessible RadioGroup container conforming to WAI-ARIA Radio Group pattern (DEV-SPEC §4.2).
 * Wraps single-select OptionCard items with role="radiogroup", accessible labeling,
 * and keyboard arrow navigation (ArrowDown/ArrowRight for next, ArrowUp/ArrowLeft for prev).
 */
export function RadioGroup({
  label,
  ariaLabelledBy,
  children,
  className = "flex flex-col gap-3 w-full",
  testId = "quiz-radiogroup",
}: RadioGroupProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"].includes(e.key)) {
      return;
    }

    const container = containerRef.current;
    if (!container) return;

    // Query all non-disabled radio buttons in this group
    const radios = Array.from(
      container.querySelectorAll<HTMLElement>('[role="radio"]:not([aria-disabled="true"])')
    );
    if (radios.length === 0) return;

    const currentIndex = radios.indexOf(document.activeElement as HTMLElement);
    let targetIndex = 0;

    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      targetIndex = currentIndex >= 0 ? (currentIndex + 1) % radios.length : 0;
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      targetIndex = currentIndex >= 0 ? (currentIndex - 1 + radios.length) % radios.length : radios.length - 1;
    }

    const targetRadio = radios[targetIndex];
    if (targetRadio) {
      targetRadio.focus();
      targetRadio.click();
    }
  };

  return (
    <div
      ref={containerRef}
      role="radiogroup"
      aria-label={label}
      aria-labelledby={ariaLabelledBy}
      data-testid={testId}
      onKeyDown={handleKeyDown}
      className={className}
    >
      {children}
    </div>
  );
}
