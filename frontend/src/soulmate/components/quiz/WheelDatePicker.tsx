"use client";

import React, { useEffect, useMemo, useRef } from "react";

/**
 * Wheel-style date-of-birth picker (owner-directed q08 redesign, 2026-09-29).
 *
 * Three snap-scroll columns (MONTH / DAY / YEAR) with a center-selected row and
 * a "SELECTED <date>" pill, matching the owner-supplied reference. Produces a
 * plain YYYY-MM-DD string through onChange — the submitAnswer contract, zodiac
 * derivation (SP-204) and restore-on-refresh flow are unchanged; this is an
 * input-UX swap only. Day lists adapt to the selected month/year (leap years),
 * clamping an out-of-range day instead of emitting an invalid date.
 */

const ROW_HEIGHT = 44;
const DEFAULT_DOB = { year: 1995, month: 5, day: 15 } as const;

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function getDaysInMonth(year: number, monthIndex: number): number {
  return new Date(year, monthIndex + 1, 0).getDate();
}

export function parseDateValue(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  if (month < 0 || month > 11) return null;
  if (day < 1 || day > getDaysInMonth(year, month)) return null;
  return { year, month, day };
}

export function serializeDateValue(year: number, monthIndex: number, day: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(monthIndex + 1)}-${pad(day)}`;
}

interface WheelColumnProps {
  ariaLabel: string;
  headerLabel: string;
  items: string[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  align: "start" | "center" | "end";
  flexClassName: string;
}

function WheelColumn({
  ariaLabel,
  headerLabel,
  items,
  selectedIndex,
  onSelect,
  align,
  flexClassName,
}: WheelColumnProps) {
  const listRef = useRef<HTMLDivElement | null>(null);

  // Keep the scroll position on the selected row when the selection moves
  // programmatically (restore, month-length clamp).
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const target = selectedIndex * ROW_HEIGHT;
    if (Math.abs(el.scrollTop - target) < 2) return;
    el.scrollTo({ top: target });
  }, [selectedIndex, items.length]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const idx = Math.min(items.length - 1, Math.max(0, Math.round(el.scrollTop / ROW_HEIGHT)));
    if (idx !== selectedIndex) onSelect(idx);
  };

  const alignClass =
    align === "start"
      ? "justify-start pl-6"
      : align === "end"
      ? "justify-end pr-6"
      : "justify-center";

  return (
    <div className={`min-w-0 ${flexClassName}`}>
      <div className="mb-2 text-center text-[11px] font-bold tracking-[0.14em] text-neutral-400">
        {headerLabel}
      </div>
      <div className="relative">
        {/* Center selection band, under the scrolling text */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-1/2 z-0 h-[44px] -translate-y-1/2 rounded-2xl bg-white shadow-[0_12px_30px_rgba(36,26,74,0.14)] ring-1 ring-black/5"
        />
        <div
          ref={listRef}
          role="listbox"
          aria-label={ariaLabel}
          onScroll={handleScroll}
          className="relative z-10 h-[220px] snap-y snap-mandatory overflow-y-scroll overscroll-contain py-[88px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map((label, i) => {
            const distance = Math.abs(i - selectedIndex);
            const tone =
              distance === 0
                ? "text-neutral-900 font-bold"
                : distance === 1
                ? "text-neutral-400 font-medium"
                : "text-neutral-300 font-medium";
            return (
              <div
                key={`${label}-${i}`}
                role="option"
                aria-selected={i === selectedIndex}
                className={`flex h-[44px] shrink-0 snap-center select-none items-center text-[19px] leading-none ${alignClass} ${tone}`}
              >
                {label}
              </div>
            );
          })}
        </div>
        {/* Edge fades toward the card background */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 z-20 h-[70px] bg-gradient-to-b from-white via-white/70 to-transparent"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 z-20 h-[70px] bg-gradient-to-t from-white via-white/70 to-transparent"
        />
      </div>
    </div>
  );
}

export function WheelDatePicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const currentYear = new Date().getFullYear();
  // Birth-year span: one century back through the current year. This is an
  // input-range convenience only; AGE-01 (minimum age rule) stays open and is
  // not enforced here.
  const years = useMemo(
    () => Array.from({ length: 101 }, (_, i) => currentYear - 100 + i),
    [currentYear]
  );

  const parsed = parseDateValue(value);
  // An empty/invalid stored value falls back to the picker default and syncs
  // the controlled value on mount so Next is never stuck disabled.
  const effective = parsed ?? DEFAULT_DOB;
  const clampedYear = Math.min(Math.max(effective.year, years[0]), years[years.length - 1]);
  const maxDay = getDaysInMonth(clampedYear, effective.month);
  const day = Math.min(effective.day, maxDay);

  useEffect(() => {
    if (!parsed || clampedYear !== effective.year || parsed.day !== day) {
      onChange(serializeDateValue(clampedYear, effective.month, day));
    }
    // Runs when the controlled value changes (mount sync, restore, clamp).
  }, [value]);

  const setYMD = (year: number, monthIndex: number, d: number) =>
    onChange(serializeDateValue(year, monthIndex, d));

  const dayItems = Array.from({ length: maxDay }, (_, i) => String(i + 1));

  return (
    <div
      className="w-full"
      role="group"
      aria-label="Your birth date"
      data-testid="dob-wheel-picker"
    >
      {/* Selected-date pill */}
      <div className="mx-auto mb-4 flex w-fit items-center gap-2.5 rounded-full bg-white px-5 py-2.5 shadow-sm ring-1 ring-black/5">
        <span className="h-2 w-2 rounded-full bg-amber-500" aria-hidden />
        <span className="text-[11px] font-bold tracking-[0.08em] text-neutral-400">SELECTED</span>
        <span className="text-[15px] font-bold text-neutral-900">
          {MONTH_NAMES[effective.month]} {day}, {clampedYear}
        </span>
      </div>

      {/* Three-column wheel card */}
      <div
        className={`w-full rounded-3xl bg-white px-4 py-5 shadow-sm ring-1 ring-black/5 ${
          disabled ? "pointer-events-none opacity-60" : ""
        }`}
      >
        <div className="flex items-stretch gap-2">
          <WheelColumn
            ariaLabel="Birth month"
            headerLabel="MONTH"
            items={MONTH_NAMES}
            selectedIndex={effective.month}
            onSelect={(i) =>
              setYMD(clampedYear, i, Math.min(day, getDaysInMonth(clampedYear, i)))
            }
            align="start"
            flexClassName="flex-[1.35]"
          />
          <WheelColumn
            ariaLabel="Birth day"
            headerLabel="DAY"
            items={dayItems}
            selectedIndex={day - 1}
            onSelect={(i) => setYMD(clampedYear, effective.month, i + 1)}
            align="center"
            flexClassName="flex-1"
          />
          <WheelColumn
            ariaLabel="Birth year"
            headerLabel="YEAR"
            items={years.map(String)}
            selectedIndex={clampedYear - years[0]}
            onSelect={(i) => setYMD(years[i], effective.month, day)}
            align="end"
            flexClassName="flex-1"
          />
        </div>
      </div>
    </div>
  );
}
