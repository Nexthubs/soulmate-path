import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  WheelDatePicker,
  getDaysInMonth,
  parseDateValue,
  serializeDateValue,
} from "../src/soulmate/components/quiz/WheelDatePicker";

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
