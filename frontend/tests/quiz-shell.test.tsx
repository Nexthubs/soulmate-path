import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QuizShell, QuizNextButton } from "../src/soulmate/components/quiz/QuizShell";

// Mock next/navigation
const mockBack = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    back: mockBack,
    push: vi.fn(),
  }),
}));

describe("SP-102: Shared Quiz Layout Shell (QuizShell)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Header & Title / Subtitle Rendering", () => {
    it("renders question title and back navigation by default", () => {
      const html = renderToStaticMarkup(
        <QuizShell title="Select your gender">
          <div data-testid="test-content">Option content</div>
        </QuizShell>
      );

      // Question title matching Figma 102:127
      expect(html).toContain("Select your gender");
      expect(html).toContain("data-testid=\"quiz-back-button\"");
      expect(html).toContain("aria-label=\"Go back to previous step\"");
      expect(html).toContain("data-testid=\"test-content\"");
    });

    it("renders optional subtitle when provided (e.g. Q08 Date helper)", () => {
      const html = renderToStaticMarkup(
        <QuizShell
          title="What's your date of birth?"
          subtitle="Your birth date reveals your core personality traits, needs and desires."
        >
          <div>Date picker</div>
        </QuizShell>
      );

      expect(html).toContain("What&#x27;s your date of birth?");
      expect(html).toContain("Your birth date reveals your core personality traits, needs and desires.");
    });

    it("hides back button when showBack is false", () => {
      const html = renderToStaticMarkup(
        <QuizShell title="First Question" showBack={false}>
          <div>Content</div>
        </QuizShell>
      );

      expect(html).not.toContain("data-testid=\"quiz-back-button\"");
    });

    it("disables (not hides) the back button while back is in-flight, keeping content rendered", () => {
      const html = renderToStaticMarkup(
        <QuizShell title="Select your gender" backDisabled>
          <div data-testid="test-content">Option content</div>
        </QuizShell>
      );

      // The in-flight back keeps the current question rendered — only the
      // button is disabled (flash-free back navigation, DEV-SPEC §4.2).
      expect(html).toContain("data-testid=\"quiz-back-button\"");
      expect(html).toContain("disabled");
      expect(html).toContain("data-testid=\"test-content\"");
    });
  });

  describe("Shared Support for Diverse Question Types (Acceptance Criteria)", () => {
    it("renders Single-Choice questions inside the shell", () => {
      const html = renderToStaticMarkup(
        <QuizShell title="Select your gender">
          <div data-testid="single-choice-options">
            <button type="button">Male</button>
            <button type="button">Female</button>
          </div>
        </QuizShell>
      );

      expect(html).toContain("data-testid=\"single-choice-options\"");
      expect(html).toContain("Male");
      expect(html).toContain("Female");
      // Single choice does not require bottom action
      expect(html).not.toContain("footer");
    });

    it("renders Date question (Q08) with date input and bottom Next button", () => {
      const html = renderToStaticMarkup(
        <QuizShell
          title="What's your date of birth?"
          subtitle="Your birth date reveals your core personality traits, needs and desires."
          bottomAction={
            <QuizNextButton
              onClick={() => {}}
              disabled={false}
              label="Next"
              ariaLabel="Confirm date and continue"
            />
          }
        >
          <div data-testid="date-picker-input">
            <input type="date" defaultValue="1995-06-15" />
          </div>
        </QuizShell>
      );

      expect(html).toContain("data-testid=\"date-picker-input\"");
      expect(html).toContain("<footer");
      expect(html).toContain("Next");
      expect(html).toContain("aria-label=\"Confirm date and continue\"");
    });

    it("renders Multi-Choice question (Q18) with multiple options and bottom action", () => {
      const html = renderToStaticMarkup(
        <QuizShell
          title="What life goals do you hope to achieve with your soulmate?"
          subtitle="Choose all that apply"
          bottomAction={
            <QuizNextButton
              onClick={() => {}}
              disabled={false}
              label="Next"
              ariaLabel="Save selected goals and proceed"
            />
          }
        >
          <div data-testid="multi-choice-options">
            <div>Building a family</div>
            <div>Traveling the world</div>
            <div>Creating a business</div>
          </div>
        </QuizShell>
      );

      expect(html).toContain("data-testid=\"multi-choice-options\"");
      expect(html).toContain("Building a family");
      expect(html).toContain("Traveling the world");
      expect(html).toContain("Next");
    });
  });

  describe("Bottom Action & Next Button States", () => {
    it("renders disabled state on Next button when required", () => {
      const html = renderToStaticMarkup(
        <QuizNextButton onClick={() => {}} disabled={true} label="Next" />
      );

      expect(html).toContain("disabled=\"\"");
      expect(html).toContain("aria-disabled=\"true\"");
      expect(html).toContain("cursor-not-allowed");
    });

    it("renders loading state with spinner on Next button", () => {
      const html = renderToStaticMarkup(
        <QuizNextButton onClick={() => {}} loading={true} />
      );

      expect(html).toContain("Saving...");
      expect(html).toContain("animate-spin");
    });
  });

  describe("Loading & Error States (DEV-SPEC §4.2)", () => {
    it("renders loading skeleton during transition and marks aria-busy", () => {
      const html = renderToStaticMarkup(
        <QuizShell title="Loading next step..." isLoading={true}>
          <div data-testid="should-be-hidden">Hidden content</div>
        </QuizShell>
      );

      expect(html).toContain("data-testid=\"quiz-loading-skeleton\"");
      expect(html).toContain("aria-busy=\"true\"");
      expect(html).not.toContain("data-testid=\"should-be-hidden\"");
    });

    it("renders non-blocking error banner with retry option", () => {
      const html = renderToStaticMarkup(
        <QuizShell
          title="Network test"
          error={{ message: "Failed to save answer. Please check connection.", onRetry: () => {} }}
        >
          <div data-testid="interactive-options">Options stay interactive</div>
        </QuizShell>
      );

      expect(html).toContain("data-testid=\"quiz-error-banner\"");
      expect(html).toContain("Failed to save answer. Please check connection.");
      expect(html).toContain("Retry");
      // Interactive content remains on screen for in-place retry per DEV-SPEC §4.2
      expect(html).toContain("data-testid=\"interactive-options\"");
    });
  });
});
