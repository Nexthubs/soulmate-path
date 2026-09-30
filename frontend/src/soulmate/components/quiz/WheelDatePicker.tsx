"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Wheel-style date-of-birth picker (owner-directed q08 redesign, 2026-09-29;
 * batch-4 state isolation per `docs/UI-IMPROVEMENT-EXECUTION-PLAN.md` §8).
 *
 * Three snap-scroll columns (MONTH / DAY / YEAR) under ONE full-width center
 * selection band, with a "SELECTED <date>" pill. Produces a plain YYYY-MM-DD
 * string through onChange — the submitAnswer contract, zodiac derivation
 * (SP-204) and restore-on-refresh flow are unchanged.
 *
 * Batch-4 state isolation:
 * - the full date draft lives INSIDE this component; column scrolls/taps update
 *   only the draft (the SELECTED pill reflects it instantly) and the parent is
 *   notified exactly ONCE per settle — never per row;
 * - a column settles via `scrollend` where the browser supports it, otherwise a
 *   ~120ms no-new-scroll-event fallback; settling checks the FINAL position and
 *   snaps it exactly before reporting stability (RAF/snap is never treated as
 *   settled by itself);
 * - while any column is moving, `onMovingChange(true)` lets the parent disable
 *   Next, and the settled draft is committed once when all columns are stable;
 * - programmatic moves (mount, restore, month-length clamp) position DIRECTLY
 *   (no glide) and are flagged so their passing rows never become the committed
 *   value; user far-row taps glide smoothly with the same protection;
 * - an external `value` change (restore, Back) always overrides the local draft
 *   and clears pending settle work; timers are cleared on unmount/disable.
 *
 * Day lists adapt to the selected month/year (leap years), clamping an
 * out-of-range day instead of emitting an invalid date. Native scrolling and
 * scroll-snap are preserved; no virtualization.
 */

const ROW_HEIGHT = 44;
const WHEEL_HEIGHT = ROW_HEIGHT * 5;
const DEFAULT_DOB = { year: 1995, month: 5, day: 15 } as const;
/** No-new-scroll-event fallback for browsers without `scrollend` (§8 item 2). */
const SETTLE_FALLBACK_MS = 120;
/** Bounded safety window for tap-glides on browsers without `scrollend`. */
const GLIDE_SETTLE_FALLBACK_MS = 3000;
/** Suppress window for programmatic instant scrolls' own scroll events. */
const PROGRAMMATIC_SCROLL_MS = 150;

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

/** Clamp a year/month/day triple into a valid in-range date (§8 item 6). */
export function clampYMD(
  year: number,
  monthIndex: number,
  day: number,
  minYear: number,
  maxYear: number
): { year: number; month: number; day: number } {
  const clampedYear = Math.min(Math.max(Math.round(year), minYear), maxYear);
  const clampedMonth = Math.min(Math.max(Math.round(monthIndex), 0), 11);
  const maxDay = getDaysInMonth(clampedYear, clampedMonth);
  const clampedDay = Math.min(Math.max(Math.round(day), 1), maxDay);
  return { year: clampedYear, month: clampedMonth, day: clampedDay };
}

/**
 * Pure reconcile of an externally controlled value against the wheel's range
 * (audit P2): returns the draft the columns should show and — when the value
 * was invalid/empty OR valid but outside the year range — the clamped date the
 * parent must adopt so display == submission.
 */
export function reconcileExternalValue(
  value: string,
  minYear: number,
  maxYear: number
): { draft: { year: number; month: number; day: number }; emitValue: string | null } {
  const parsed = parseDateValue(value);
  const base = parsed ?? DEFAULT_DOB;
  const next = clampYMD(base.year, base.month, base.day, minYear, maxYear);
  const emitValue =
    !parsed || base.year !== next.year || base.month !== next.month || base.day !== next.day
      ? serializeDateValue(next.year, next.month, next.day)
      : null;
  return { draft: next, emitValue };
}

const sameYMD = (
  a: { year: number; month: number; day: number },
  b: { year: number; month: number; day: number }
) => a.year === b.year && a.month === b.month && a.day === b.day;

interface WheelColumnProps {
  ariaLabel: string;
  items: string[];
  selectedIndex: number;
  /** Draft-only selection update — the parent is NOT notified per row. */
  onSelect: (index: number) => void;
  /** Column moving-state transitions (aggregated by the picker). */
  onMovingChange: (moving: boolean) => void;
  /** External reset signal (restore/clamp/disabled): clears pending settle work. */
  resetSignal: string;
  disabled?: boolean;
  align: "start" | "center" | "end";
  flexClassName: string;
}

function WheelColumn({
  ariaLabel,
  items,
  selectedIndex,
  onSelect,
  onMovingChange,
  resetSignal,
  disabled = false,
  align,
  flexClassName,
}: WheelColumnProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const programmaticUntilRef = useRef(0);
  /** Non-null while a tap-glide is in flight: scrollTop target of the glide. */
  const glideTargetRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const movingRef = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onMovingChangeRef = useRef(onMovingChange);
  onMovingChangeRef.current = onMovingChange;

  // `scrollend` is the verified end event on Chromium 114+; the timed no-scroll
  // fallback covers the rest (§8 item 2).
  const supportsScrollend = useMemo(
    () => typeof window !== "undefined" && "onscrollend" in window,
    []
  );

  const clearSettleTimer = useCallback(() => {
    if (settleTimerRef.current !== null) {
      clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
  }, []);

  const setMoving = useCallback(
    (moving: boolean) => {
      if (movingRef.current === moving) return;
      movingRef.current = moving;
      onMovingChangeRef.current(moving);
    },
    []
  );

  const settle = useCallback(() => {
    settleTimerRef.current = null;
    const el = listRef.current;
    if (!el) {
      setMoving(false);
      return;
    }
    const clampedIdx = Math.min(
      items.length - 1,
      Math.max(0, Math.round(el.scrollTop / ROW_HEIGHT))
    );
    const target = clampedIdx * ROW_HEIGHT;
    if (Math.abs(el.scrollTop - target) > 1) {
      // §8 item 3: the snap is not verified until the final position matches —
      // correct exactly (a new scroll event re-runs settle) and stay moving.
      el.scrollTo({ top: target, behavior: "auto" });
      if (!supportsScrollend) {
        settleTimerRef.current = window.setTimeout(settle, SETTLE_FALLBACK_MS);
      }
      return;
    }
    setMoving(false);
  }, [items.length, setMoving, supportsScrollend]);

  const scheduleSettle = useCallback(
    (delayMs: number) => {
      clearSettleTimer();
      settleTimerRef.current = window.setTimeout(settle, delayMs);
    },
    [clearSettleTimer, settle]
  );

  // Programmatic positioning (mount, restore, month-length clamp): DIRECT
  // placement, never a glide (§8 item 4). The instant scroll's own events are
  // flagged so passing rows cannot become the committed value, and any pending
  // user-settle work is cancelled (§8 item 7).
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const target = selectedIndex * ROW_HEIGHT;
    if (Math.abs(el.scrollTop - target) <= ROW_HEIGHT * 0.6) return;
    programmaticUntilRef.current = Date.now() + PROGRAMMATIC_SCROLL_MS;
    clearSettleTimer();
    setMoving(false);
    el.scrollTo({ top: target, behavior: "auto" });
  }, [selectedIndex, items.length, clearSettleTimer, setMoving]);

  // External reset (value restore / disabled): drop pending settle work AND any
  // in-flight glide target so a restored value is never overwritten (§8 item 7).
  useEffect(() => {
    glideTargetRef.current = null;
    clearSettleTimer();
    setMoving(false);
  }, [resetSignal, clearSettleTimer, setMoving]);

  useEffect(() => {
    if (!disabled) return;
    glideTargetRef.current = null;
    clearSettleTimer();
    setMoving(false);
  }, [disabled, clearSettleTimer, setMoving]);

  useEffect(() => {
    return () => {
      if (settleTimerRef.current !== null) clearTimeout(settleTimerRef.current);
    };
  }, []);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    // Tap-glide in flight: every event before the target position is reached is
    // a PASSING row — never update the draft from it (§8 item 4). Arrival is
    // position-based, not time-based, so glides of any length settle correctly.
    if (glideTargetRef.current != null) {
      const glideTarget = glideTargetRef.current;
      if (Math.abs(el.scrollTop - glideTarget) > 1) return;
      glideTargetRef.current = null; // arrived at the tapped row
      settle();
      return;
    }
    if (Date.now() < programmaticUntilRef.current) return; // instant programmatic events
    // User-originated scroll: update the local draft only (§8 item 1) —
    // the parent is notified once on settle, never per row.
    const idx = Math.min(items.length - 1, Math.max(0, Math.round(el.scrollTop / ROW_HEIGHT)));
    if (idx !== selectedIndex) onSelectRef.current(idx);
    setMoving(true);
    if (!supportsScrollend) scheduleSettle(SETTLE_FALLBACK_MS);
  };

  const handleScrollEnd = () => {
    // A glide's scrollend is its arrival: let handleScroll's position check
    // clear the glide target first; settle from wherever the column ended.
    settle();
  };

  // React has no synthetic `scrollend`; bind natively when supported.
  useEffect(() => {
    const el = listRef.current;
    if (!el || !supportsScrollend) return;
    el.addEventListener("scrollend", handleScrollEnd);
    return () => el.removeEventListener("scrollend", handleScrollEnd);
  }, [supportsScrollend, settle]);

  // Tap-to-select: a far-row tap glides smoothly (§8 item 4) as a POSITION-
  // tracked programmatic move — passing rows are ignored by handleScroll until
  // the tapped row's exact position is reached, so they can never become the
  // committed value; the DRAFT is set to the tapped row up front and the settle
  // after arrival commits it once (§8 item 5).
  const handleItemClick = (index: number) => {
    const el = listRef.current;
    if (!el) return;
    const target = index * ROW_HEIGHT;
    if (Math.abs(el.scrollTop - target) <= ROW_HEIGHT * 0.6) {
      // Within the selection band: apply immediately, nothing moves.
      if (index !== selectedIndex) onSelectRef.current(index);
      return;
    }
    clearSettleTimer();
    glideTargetRef.current = target;
    if (index !== selectedIndex) onSelectRef.current(index);
    setMoving(true);
    el.scrollTo({ top: target, behavior: "smooth" });
    if (!supportsScrollend) {
      // Bounded safety net: browsers without scrollend get a generous glide
      // window; if the glide still hasn't arrived (jank), settle where it is.
      scheduleSettle(GLIDE_SETTLE_FALLBACK_MS);
    }
  };

  const alignClass =
    align === "start"
      ? "justify-start pl-5"
      : align === "end"
      ? "justify-end pr-5"
      : "justify-center";

  return (
    <div className={`min-w-0 ${flexClassName}`}>
      <div
        ref={listRef}
        role="listbox"
        aria-label={ariaLabel}
        onScroll={handleScroll}
        style={{ height: WHEEL_HEIGHT }}
        className="relative z-10 snap-y snap-mandatory overflow-y-scroll overscroll-contain py-[88px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
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
              onClick={() => handleItemClick(i)}
              className={`flex h-[44px] shrink-0 cursor-pointer snap-center select-none items-center text-[17px] leading-none ${alignClass} ${tone}`}
            >
              {label}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WheelDatePicker({
  value,
  onChange,
  onMovingChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Any column is between scroll-start and settle (parent disables Next). */
  onMovingChange?: (moving: boolean) => void;
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
  const minYear = years[0];
  const maxYear = years[years.length - 1];

  // The full date draft lives here (§8 item 1): column interactions update it
  // locally; the parent receives exactly one onChange per settle (§8 item 5).
  const [draft, setDraft] = useState(() => {
    const parsed = parseDateValue(value);
    const base = parsed ?? DEFAULT_DOB;
    return clampYMD(base.year, base.month, base.day, minYear, maxYear);
  });
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const dirtyRef = useRef(false);
  const [anyMoving, setAnyMoving] = useState(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onMovingChangeRef = useRef(onMovingChange);
  onMovingChangeRef.current = onMovingChange;
  const columnMovingRef = useRef<{ month: boolean; day: boolean; year: boolean }>({
    month: false,
    day: false,
    year: false,
  });

  // External value changes (restore, Back, parent clamp) ALWAYS override the
  // local draft (§8 item 6/7) — and when clamping changed the value, the
  // clamped date is synced back to the parent so the displayed and the
  // submitted dates stay identical (audit P2).
  useEffect(() => {
    const { draft: next, emitValue } = reconcileExternalValue(value, minYear, maxYear);
    setDraft((prev) => (sameYMD(prev, next) ? prev : next));
    if (emitValue) onChangeRef.current(emitValue);
    // Runs when the controlled value changes (mount sync, restore, clamp).
  }, [value, minYear, maxYear]);

  const handleColumnSelect = useCallback(
    (column: "month" | "day" | "year") => (index: number) => {
      setDraft((prev) => {
        if (column === "month") {
          return clampYMD(prev.year, index, prev.day, minYear, maxYear);
        }
        if (column === "day") {
          return clampYMD(prev.year, prev.month, index + 1, minYear, maxYear);
        }
        return clampYMD(minYear + index, prev.month, prev.day, minYear, maxYear);
      });
      dirtyRef.current = true;
    },
    [minYear, maxYear]
  );

  const handleColumnMoving = useCallback(
    (column: "month" | "day" | "year") => (moving: boolean) => {
      columnMovingRef.current[column] = moving;
      const next = Object.values(columnMovingRef.current).some(Boolean);
      setAnyMoving(next);
      onMovingChangeRef.current?.(next);
      // §8 item 5: when the LAST column settles, commit the whole draft once.
      if (!next && dirtyRef.current) {
        dirtyRef.current = false;
        const d = draftRef.current;
        onChangeRef.current(serializeDateValue(d.year, d.month, d.day));
      }
    },
    []
  );

  const dayItems = Array.from({ length: getDaysInMonth(draft.year, draft.month) }, (_, i) =>
    String(i + 1)
  );

  const headerClass = "text-center text-[11px] font-bold tracking-[0.14em] text-neutral-400";

  return (
    <div
      className="w-full"
      role="group"
      aria-label="Your birth date"
      data-testid="dob-wheel-picker"
      data-moving={anyMoving ? "true" : "false"}
    >
      {/* Selected-date pill — reflects the LOCAL draft for instant feedback */}
      <div className="mx-auto mb-4 flex w-fit items-center gap-2.5 rounded-full bg-white px-5 py-2.5 shadow-sm ring-1 ring-black/5">
        <span className="h-2 w-2 rounded-full bg-amber-500" aria-hidden />
        <span className="text-[11px] font-bold tracking-[0.08em] text-neutral-400">SELECTED</span>
        <span className="text-[15px] font-bold text-neutral-900">
          {MONTH_NAMES[draft.month]} {draft.day}, {draft.year}
        </span>
      </div>

      {/* Three-column wheel card */}
      <div
        className={`w-full rounded-3xl bg-white px-4 py-5 shadow-sm ring-1 ring-black/5 ${
          disabled ? "pointer-events-none opacity-60" : ""
        }`}
      >
        {/* Column headers */}
        <div className="mb-2 flex items-stretch gap-2">
          <div className={`flex-[1.35] ${headerClass}`}>MONTH</div>
          <div className={`flex-1 ${headerClass}`}>DAY</div>
          <div className={`flex-1 ${headerClass}`}>YEAR</div>
        </div>

        {/* Wheels row with ONE full-width center band + edge fades */}
        <div className="relative">
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-x-1 top-1/2 z-0 h-[44px] -translate-y-1/2 rounded-2xl bg-white shadow-[0_12px_30px_rgba(36,26,74,0.14)] ring-1 ring-black/5"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 z-20 h-[70px] bg-gradient-to-b from-white via-white/70 to-transparent"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 z-20 h-[70px] bg-gradient-to-t from-white via-white/70 to-transparent"
          />
          <div className="relative z-10 flex items-stretch gap-2">
            <WheelColumn
              ariaLabel="Birth month"
              items={MONTH_NAMES}
              selectedIndex={draft.month}
              onSelect={handleColumnSelect("month")}
              onMovingChange={handleColumnMoving("month")}
              resetSignal={value}
              disabled={disabled}
              align="start"
              flexClassName="flex-[1.35]"
            />
            <WheelColumn
              ariaLabel="Birth day"
              items={dayItems}
              selectedIndex={draft.day - 1}
              onSelect={handleColumnSelect("day")}
              onMovingChange={handleColumnMoving("day")}
              resetSignal={value}
              disabled={disabled}
              align="center"
              flexClassName="flex-1"
            />
            <WheelColumn
              ariaLabel="Birth year"
              items={years.map(String)}
              selectedIndex={draft.year - minYear}
              onSelect={handleColumnSelect("year")}
              onMovingChange={handleColumnMoving("year")}
              resetSignal={value}
              disabled={disabled}
              align="end"
              flexClassName="flex-1"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
