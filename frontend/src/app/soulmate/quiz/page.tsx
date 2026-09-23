"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { QuizShell, QuizNextButton } from "@/soulmate/components/quiz/QuizShell";
import { OptionCard } from "@/soulmate/components/quiz/OptionCard";
import quizData from "@/soulmate/quiz/soulmate-quiz-v1.json";

type PreviewQuestionType = "single" | "date" | "multi";

export default function SoulmateQuizPage() {
  const router = useRouter();

  // In fixture mode, allow switching between the three core question types (Single, Date, Multi)
  const [currentType, setCurrentType] = useState<PreviewQuestionType>("single");
  const [singleValue, setSingleValue] = useState<string>("female");
  const [dateValue, setDateValue] = useState<string>("1995-06-15");
  const [multiValues, setMultiValues] = useState<string[]>(["building_a_family", "traveling_the_world"]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Retrieve questions from canonical quiz config
  const q02 = quizData.questions.find((q) => q.code === "q02")!;
  const q08 = quizData.questions.find((q) => q.code === "q08")!;
  const q18 = quizData.questions.find((q) => q.code === "q18")!;

  const handleBack = () => {
    if (currentType === "multi") {
      setCurrentType("date");
    } else if (currentType === "date") {
      setCurrentType("single");
    } else {
      router.push("/soulmate");
    }
  };

  const handleNext = () => {
    if (currentType === "single") {
      setCurrentType("date");
    } else if (currentType === "date") {
      setCurrentType("multi");
    } else {
      router.push("/soulmate/loading?step=5");
    }
  };

  return (
    <div className="relative">
      {/* Dev Switcher for testing all three question types in fixture shell */}
      <div className="absolute top-2 right-4 z-50 flex gap-1 bg-white/80 backdrop-blur-xs p-1 rounded-lg text-[10px] text-neutral-600 border border-neutral-200">
        <button
          type="button"
          onClick={() => setCurrentType("single")}
          className={`px-1.5 py-0.5 rounded ${
            currentType === "single" ? "bg-purple-600 text-white font-semibold" : "hover:bg-neutral-100"
          }`}
        >
          Single
        </button>
        <button
          type="button"
          onClick={() => setCurrentType("date")}
          className={`px-1.5 py-0.5 rounded ${
            currentType === "date" ? "bg-purple-600 text-white font-semibold" : "hover:bg-neutral-100"
          }`}
        >
          Date
        </button>
        <button
          type="button"
          onClick={() => setCurrentType("multi")}
          className={`px-1.5 py-0.5 rounded ${
            currentType === "multi" ? "bg-purple-600 text-white font-semibold" : "hover:bg-neutral-100"
          }`}
        >
          Multi
        </button>
      </div>

      {currentType === "single" && (
        <QuizShell
          title={q02.title}
          subtitle="Select one option to continue"
          onBack={handleBack}
          isLoading={isLoading}
          error={error ? { message: error, onRetry: () => setError(null) } : null}
        >
          {q02.options?.map((opt) => (
            <OptionCard
              key={opt.code}
              label={opt.label}
              selected={singleValue === opt.code}
              selectionType="single"
              onClick={() => {
                setSingleValue(opt.code);
                setTimeout(() => handleNext(), 200);
              }}
            />
          ))}
        </QuizShell>
      )}

      {currentType === "date" && (
        <QuizShell
          title={q08.title}
          subtitle={q08.subtitle}
          onBack={handleBack}
          isLoading={isLoading}
          error={error}
          bottomAction={
            <QuizNextButton
              onClick={handleNext}
              disabled={!dateValue}
              label="Next"
              ariaLabel="Confirm date and continue"
            />
          }
        >
          <div className="w-full p-6 rounded-2xl bg-white/70 border border-neutral-200/60 shadow-xs flex flex-col items-center gap-4">
            <label htmlFor="birthdate-input" className="text-xs font-medium text-neutral-600">
              Date of Birth (YYYY-MM-DD)
            </label>
            <input
              id="birthdate-input"
              type="date"
              value={dateValue}
              onChange={(e) => setDateValue(e.target.value)}
              className="w-full h-12 px-4 rounded-xl border border-neutral-300 bg-white text-neutral-900 text-center text-lg focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </QuizShell>
      )}

      {currentType === "multi" && (
        <QuizShell
          title={q18.title}
          subtitle="Choose all that apply"
          onBack={handleBack}
          isLoading={isLoading}
          error={error}
          bottomAction={
            <QuizNextButton
              onClick={handleNext}
              disabled={multiValues.length === 0}
              label="Next"
              ariaLabel="Save selected goals and proceed"
            />
          }
        >
          {q18.options?.map((opt) => (
            <OptionCard
              key={opt.code}
              label={opt.label}
              selected={multiValues.includes(opt.code)}
              selectionType="multi"
              onClick={() => {
                setMultiValues((prev) =>
                  prev.includes(opt.code)
                    ? prev.filter((c) => c !== opt.code)
                    : [...prev, opt.code]
                );
              }}
            />
          ))}
        </QuizShell>
      )}
    </div>
  );
}
