import { describe, it, expect } from "vitest";
import {
  calculateZodiacSign,
  ZODIAC_DEFINITIONS,
  ZodiacSignCode,
} from "../src/soulmate/domain/zodiac";

describe("Frontend Zodiac Domain Engine (SP-204)", () => {
  const boundaryCases: Array<{
    dateStr: string;
    expectedCode: ZodiacSignCode;
    expectedName: string;
    expectedLabel: string;
  }> = [
    // Aries: 03-21 ~ 04-19
    { dateStr: "1995-03-21", expectedCode: "aries", expectedName: "Aries", expectedLabel: "Aries Sun" },
    { dateStr: "1995-04-19", expectedCode: "aries", expectedName: "Aries", expectedLabel: "Aries Sun" },
    // Taurus: 04-20 ~ 05-20
    { dateStr: "1995-04-20", expectedCode: "taurus", expectedName: "Taurus", expectedLabel: "Taurus Sun" },
    { dateStr: "1995-05-20", expectedCode: "taurus", expectedName: "Taurus", expectedLabel: "Taurus Sun" },
    // Gemini: 05-21 ~ 06-21
    { dateStr: "1995-05-21", expectedCode: "gemini", expectedName: "Gemini", expectedLabel: "Gemini Sun" },
    { dateStr: "1995-06-21", expectedCode: "gemini", expectedName: "Gemini", expectedLabel: "Gemini Sun" },
    // Cancer: 06-22 ~ 07-22
    { dateStr: "1995-06-22", expectedCode: "cancer", expectedName: "Cancer", expectedLabel: "Cancer Sun" },
    { dateStr: "1995-07-22", expectedCode: "cancer", expectedName: "Cancer", expectedLabel: "Cancer Sun" },
    // Leo: 07-23 ~ 08-22
    { dateStr: "1995-07-23", expectedCode: "leo", expectedName: "Leo", expectedLabel: "Leo Sun" },
    { dateStr: "1995-08-22", expectedCode: "leo", expectedName: "Leo", expectedLabel: "Leo Sun" },
    // Virgo: 08-23 ~ 09-22
    { dateStr: "1995-08-23", expectedCode: "virgo", expectedName: "Virgo", expectedLabel: "Virgo Sun" },
    { dateStr: "1995-09-22", expectedCode: "virgo", expectedName: "Virgo", expectedLabel: "Virgo Sun" },
    // Libra: 09-23 ~ 10-23
    { dateStr: "1995-09-23", expectedCode: "libra", expectedName: "Libra", expectedLabel: "Libra Sun" },
    { dateStr: "1995-10-23", expectedCode: "libra", expectedName: "Libra", expectedLabel: "Libra Sun" },
    // Scorpio: 10-24 ~ 11-21
    { dateStr: "1995-10-24", expectedCode: "scorpio", expectedName: "Scorpio", expectedLabel: "Scorpio Sun" },
    { dateStr: "1995-11-21", expectedCode: "scorpio", expectedName: "Scorpio", expectedLabel: "Scorpio Sun" },
    // Sagittarius: 11-22 ~ 12-20
    { dateStr: "1995-11-22", expectedCode: "sagittarius", expectedName: "Sagittarius", expectedLabel: "Sagittarius Sun" },
    { dateStr: "1995-12-20", expectedCode: "sagittarius", expectedName: "Sagittarius", expectedLabel: "Sagittarius Sun" },
    // Capricorn: 12-21 ~ 01-20
    { dateStr: "1995-12-21", expectedCode: "capricorn", expectedName: "Capricorn", expectedLabel: "Capricorn Sun" },
    { dateStr: "1995-12-31", expectedCode: "capricorn", expectedName: "Capricorn", expectedLabel: "Capricorn Sun" },
    { dateStr: "1996-01-01", expectedCode: "capricorn", expectedName: "Capricorn", expectedLabel: "Capricorn Sun" },
    { dateStr: "1996-01-20", expectedCode: "capricorn", expectedName: "Capricorn", expectedLabel: "Capricorn Sun" },
    // Aquarius: 01-21 ~ 02-19
    { dateStr: "1996-01-21", expectedCode: "aquarius", expectedName: "Aquarius", expectedLabel: "Aquarius Sun" },
    { dateStr: "1996-02-19", expectedCode: "aquarius", expectedName: "Aquarius", expectedLabel: "Aquarius Sun" },
    // Pisces: 02-20 ~ 03-20
    { dateStr: "1996-02-20", expectedCode: "pisces", expectedName: "Pisces", expectedLabel: "Pisces Sun" },
    { dateStr: "1995-02-28", expectedCode: "pisces", expectedName: "Pisces", expectedLabel: "Pisces Sun" },
    { dateStr: "1996-02-29", expectedCode: "pisces", expectedName: "Pisces", expectedLabel: "Pisces Sun" }, // Leap year
    { dateStr: "1996-03-20", expectedCode: "pisces", expectedName: "Pisces", expectedLabel: "Pisces Sun" },
  ];

  it.each(boundaryCases)(
    "calculates $expectedName for $dateStr",
    ({ dateStr, expectedCode, expectedName, expectedLabel }) => {
      const result = calculateZodiacSign(dateStr);
      expect(result.code).toBe(expectedCode);
      expect(result.name).toBe(expectedName);
      expect(result.sunLabel).toBe(expectedLabel);
    }
  );

  it("calculates zodiac from Date object correctly", () => {
    const d = new Date(Date.UTC(1994, 7, 25)); // Aug 25 -> Virgo
    const result = calculateZodiacSign(d);
    expect(result.code).toBe("virgo");
    expect(result.name).toBe("Virgo");
    expect(result.sunLabel).toBe("Virgo Sun");
  });

  it("throws descriptive error on malformed date string", () => {
    expect(() => calculateZodiacSign("invalid-date")).toThrowError(
      /Invalid birth date format/
    );
  });
});
