/**
 * Canonical Quiz Configuration TypeScript definitions (DEV-SPEC §4.1–4.6).
 */

export type QuestionType = "single" | "multi" | "date";

export interface QuizOption {
  code: string;
  label: string;
}

export interface QuizQuestion {
  code: string;
  order: number;
  type: QuestionType;
  title: string;
  required: boolean;
  result_key: string;
  subtitle?: string;
  min_select?: number;
  max_select?: number | null;
  options?: QuizOption[];
}

export interface QuizConfig {
  version: string;
  questions: QuizQuestion[];
}
