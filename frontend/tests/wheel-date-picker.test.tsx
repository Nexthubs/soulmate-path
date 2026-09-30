import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  WheelDatePicker,
  clampYMD,
  getDaysInMonth,
  parseDateValue,
  reconcileExternalValue,
  serializeDateValue,
} from "../src/soulmate/components/quiz/WheelDatePicker";

describe("WheelDatePicker external-value reconcile (audit P2: display == submitted)", () => {
  it("keeps a valid in-range value without emitting a parent sync", () => {
    const r = reconcileExternalValue("1995-06-15", 1926, 2026);
    expect(r.draft).toEqual({ year: 1995, month: 5, day: 15 });
    expect(r.emitValue).toBeNull();
  });

  it("clamps a valid but out-of-range date and emits it back to the parent", () => {
    const r = reconcileExternalValue("1900-02-28", 1926, 2026);
    expect(r.draft).toEqual({ year: 1926, month: 1, day: 28 });
    expect(r.emitValue).toBe("1926-02-28");
  });

  it("emits the picker default for an empty/invalid stored value", () => {
    const r = reconcileExternalValue("", 1926, 2026);
    expect(r.draft).toEqual({ year: 1995, month: 5, day: 15 });
    expect(r.emitValue).toBe("1995-06-15");
  });

  it("emits the picker default for an unparseable date (invalid day/non-leap)", () => {
    // parseDateValue rejects day>month-length and non-leap Feb-29 outright,
    // so those fall into the same default-sync branch as empty values.
    const r = reconcileExternalValue("2023-04-31", 1926, 2026);
    expect(r.draft).toEqual({ year: 1995, month: 5, day: 15 });
    expect(r.emitValue).toBe("1995-06-15");
  });

  it("keeps a leap-day value that is in range and valid", () => {
    const r = reconcileExternalValue("2024-02-29", 1926, 2026);
    expect(r.draft).toEqual({ year: 2024, month: 1, day: 29 });
    expect(r.emitValue).toBeNull();
  });
});

describe("WheelDatePicker draft clamping (batch 4 §8 item 6)", () => {
  it("clamps the day when the month has fewer days (Jan 31 → Feb)", () => {
    expect(clampYMD(2023, 1, 31, 1926, 2026)).toEqual({ year: 2023, month: 1, day: 28 });
  });

  it("keeps Feb 29 in leap years and clamps it in common years", () => {
    expect(clampYMD(2024, 1, 29, 1926, 2026)).toEqual({ year: 2024, month: 1, day: 29 });
    expect(clampYMD(2023, 1, 29, 1926, 2026)).toEqual({ year: 2023, month: 1, day: 28 });
    expect(clampYMD(2000, 1, 29, 1926, 2026)).toEqual({ year: 2000, month: 1, day: 29 });
    // 1900 is outside the picker range — the year clamps to minYear (1926, common Feb)
    expect(clampYMD(1900, 1, 29, 1926, 2026)).toEqual({ year: 1926, month: 1, day: 28 });
  });

  it("clamps 30/31-day months down to 30-day months", () => {
    expect(clampYMD(2024, 3, 31, 1926, 2026)).toEqual({ year: 2024, month: 3, day: 30 });
  });

  it("clamps the year into the picker range and the month into 0-11", () => {
    expect(clampYMD(1800, 5, 15, 1926, 2026)).toEqual({ year: 1926, month: 5, day: 15 });
    expect(clampYMD(2026, 13, 15, 1926, 2026)).toEqual({ year: 2026, month: 11, day: 15 });
    expect(clampYMD(2026, -1, 15, 1926, 2026)).toEqual({ year: 2026, month: 0, day: 15 });
  });
});

describe("WheelDatePicker date helpers (owner-directed q08 redesign)", () => {
  it("getDaysInMonth covers leap-year and month boundaries", () => {
    expect(getDaysInMonth(2024, 1)).toBe(29); // Feb, leap year
    expect(getDaysInMonth(2023, 1)).toBe(28); // Feb, common year
    expect(getDaysInMonth(2000, 1)).toBe(29); // Feb, 400-year leap
    expect(getDaysInMonth(1900, 1)).toBe(28); // Feb, 100-year non-leap
    expect(getDaysInMonth(2024, 3)).toBe(30); // April
    expect(getDaysInMonth(2024, 0)).toBe(31); // January
    expect(getDaysInMonth(2024, 11)).toBe(31); // December
  });

  it("parseDateValue accepts only valid YYYY-MM-DD dates", () => {
    expect(parseDateValue("1995-06-15")).toEqual({ year: 1995, month: 5, day: 15 });
    expect(parseDateValue(" 2000-02-29 ")).toEqual({ year: 2000, month: 1, day: 29 });
    expect(parseDateValue("")).toBeNull();
    expect(parseDateValue("1995-6-15")).toBeNull(); // no zero padding
    expect(parseDateValue("2023-02-29")).toBeNull(); // non-leap Feb 29
    expect(parseDateValue("1995-13-01")).toBeNull(); // month out of range
    expect(parseDateValue("1995-00-10")).toBeNull();
  });

  it("serializeDateValue zero-pads month and day", () => {
    expect(serializeDateValue(1995, 5, 15)).toBe("1995-06-15");
    expect(serializeDateValue(2024, 0, 3)).toBe("2024-01-03");
  });
});

describe("WheelDatePicker rendering", () => {
  const noop = () => undefined;

  it("renders the three wheel columns, headers, and the SELECTED pill", () => {
    const html = renderToStaticMarkup(<WheelDatePicker value="1995-06-15" onChange={noop} />);

    expect(html).toContain('data-testid="dob-wheel-picker"');
    expect(html).toContain("MONTH");
    expect(html).toContain("DAY");
    expect(html).toContain("YEAR");
    expect(html).toContain("SELECTED");
    expect(html).toContain("June 15, 1995");
    // Month names in the month column
    expect(html).toContain("January");
    expect(html).toContain("December");
    // Wheel a11y roles
    expect((html.match(/role="listbox"/g) || []).length).toBe(3);
  });

  it("marks the selected row via aria-selected", () => {
    const html = renderToStaticMarkup(<WheelDatePicker value="1995-06-15" onChange={noop} />);
    expect((html.match(/aria-selected="true"/g) || []).length).toBe(3);
  });

  it("renders as a disabled group with reduced opacity", () => {
    const html = renderToStaticMarkup(<WheelDatePicker value="1995-06-15" onChange={noop} disabled />);
    expect(html).toContain("pointer-events-none");
    expect(html).toContain("opacity-60");
  });
});
