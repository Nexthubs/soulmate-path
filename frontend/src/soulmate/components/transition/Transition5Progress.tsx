"use client";

import React, { useEffect, useState } from "react";

export interface ProgressItem {
  id: string;
  label: string;
  targetPercent: number;
}

export interface Transition5ProgressProps {
  /**
   * Title above the progress bars. Defaults to "Preparing Your Personal Soulmate Insights".
   */
  title?: string;

  /**
   * Whether to animate bars on mount. Defaults to true.
   */
  animated?: boolean;

  /**
   * Callback fired once animation reaches the target percentages.
   */
  onAnimationComplete?: () => void;
}

const DEFAULT_ITEMS: ProgressItem[] = [
  { id: "heart", label: "Heart’s Intentions", targetPercent: 100 },
  { id: "portrait", label: "Portrait of the Soulmate", targetPercent: 85 },
  { id: "connection", label: "Connection Insights", targetPercent: 0 },
];

/**
 * Experiential Progress Component for Transition-5 (Figma Node 102:386; DEV-SPEC §5.7).
 * Displays marketing progress bars (100%, 85%, 0%) prior to payment capture.
 * NOTE: Strictly demarcated as front-end experiential pacing; not bound to real backend AI jobs.
 */
export function Transition5Progress({
  title = "Preparing Your Personal Soulmate Insights",
  animated = true,
  onAnimationComplete,
}: Transition5ProgressProps) {
  const [percentages, setPercentages] = useState<{ [key: string]: number }>(() =>
    animated
      ? { heart: 0, portrait: 0, connection: 0 }
      : { heart: 100, portrait: 85, connection: 0 }
  );

  useEffect(() => {
    if (!animated) return;

    const timer = setTimeout(() => {
      setPercentages({ heart: 100, portrait: 85, connection: 0 });
      if (onAnimationComplete) {
        onAnimationComplete();
      }
    }, 150);

    return () => clearTimeout(timer);
  }, [animated, onAnimationComplete]);

  return (
    <div className="w-full max-w-[342px] mx-auto text-left space-y-7" data-testid="transition-5-progress">
      <h2 className="font-sans font-semibold text-[24px] leading-[32px] text-center text-[#111827] mb-8">
        {title}
      </h2>

      {DEFAULT_ITEMS.map((item) => {
        const currentVal = percentages[item.id] ?? 0;
        return (
          <div key={item.id} className="space-y-2.5">
            <div className="flex justify-between items-center text-[15px] font-medium text-[#1f2937]">
              <span>{item.label}</span>
              <span className="font-semibold text-neutral-600">{item.targetPercent}%</span>
            </div>

            {/* Progress Track & Fill */}
            <div
              className="w-full h-3 rounded-full bg-[#ede9fe] overflow-hidden"
              role="progressbar"
              aria-valuenow={currentVal}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={item.label}
            >
              <div
                className="h-full bg-[#3c2a68] rounded-full transition-all duration-700 ease-out"
                style={{ width: `${currentVal}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
