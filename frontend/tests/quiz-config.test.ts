import { describe, it, expect } from "vitest";
import quizData from "../src/soulmate/quiz/soulmate-quiz-v1.json";
import { QuizConfig } from "../src/soulmate/quiz/types";

describe("Canonical Quiz Configuration (soulmate-quiz-v1)", () => {
  const config = quizData as QuizConfig;

  it("has canonical version soulmate-quiz-v1", () => {
    expect(config.version).toBe("soulmate-quiz-v1");
  });

  it("contains exactly 17 questions ordered sequentially from q02 to q18", () => {
    expect(config.questions).toHaveLength(17);
    const expectedCodes = Array.from({ length: 17 }, (_, i) => `q${String(i + 2).padStart(2, "0")}`);
    const actualCodes = config.questions.map((q) => q.code);
    expect(actualCodes).toEqual(expectedCodes);

    config.questions.forEach((q, idx) => {
      expect(q.order).toBe(idx + 2);
      expect(q.required).toBe(true);
      expect(q.title.trim().length).toBeGreaterThan(0);
      expect(q.result_key.trim().length).toBeGreaterThan(0);
    });
  });

  it("enforces Q18 is the only multi-select question", () => {
    const q18 = config.questions.find((q) => q.code === "q18");
    expect(q18).toBeDefined();
    expect(q18?.type).toBe("multi");
    expect(q18?.min_select).toBe(1);
    expect(q18?.max_select).toBeNull();
    expect(q18?.options && q18.options.length).toBeGreaterThanOrEqual(2);

    const otherMulti = config.questions.filter((q) => q.code !== "q18" && q.type === "multi");
    expect(otherMulti).toHaveLength(0);
  });

  it("enforces Q08 is the only date question", () => {
    const q08 = config.questions.find((q) => q.code === "q08");
    expect(q08).toBeDefined();
    expect(q08?.type).toBe("date");
    expect(q08?.options).toBeUndefined();
    expect(q08?.subtitle).toBeDefined();
    expect(q08?.subtitle?.length).toBeGreaterThan(0);

    const otherDate = config.questions.filter((q) => q.code !== "q08" && q.type === "date");
    expect(otherDate).toHaveLength(0);
  });

  it("enforces QUIZ-01: Q02 (user_gender) and Q03 (preferred_partner_gender) distinct result keys", () => {
    const q02 = config.questions.find((q) => q.code === "q02");
    const q03 = config.questions.find((q) => q.code === "q03");
    expect(q02?.result_key).toBe("user_gender");
    expect(q03?.result_key).toBe("preferred_partner_gender");
    expect(q02?.result_key).not.toBe(q03?.result_key);
  });

  it("enforces unique result keys across all questions", () => {
    const resultKeys = config.questions.map((q) => q.result_key);
    const uniqueKeys = new Set(resultKeys);
    expect(uniqueKeys.size).toBe(resultKeys.length);
  });

  it("enforces unique option codes within each single/multi question", () => {
    config.questions.forEach((q) => {
      if (q.options) {
        const optionCodes = q.options.map((opt) => opt.code);
        const uniqueOptionCodes = new Set(optionCodes);
        expect(uniqueOptionCodes.size).toBe(optionCodes.length);
        q.options.forEach((opt) => {
          expect(opt.code.trim().length).toBeGreaterThan(0);
          expect(opt.label.trim().length).toBeGreaterThan(0);
        });
      }
    });
  });
});
