import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { OptionCard } from "../src/soulmate/components/quiz/OptionCard";
import { RadioGroup } from "../src/soulmate/components/quiz/RadioGroup";

describe("SP-103: OptionCard Component Variants & Semantics", () => {
  describe("Visual States (Figma Nodes 102:130, 102:137)", () => {
    it("renders unselected visual state matching Figma baseline", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="An interesting soul"
          selected={false}
          onClick={() => {}}
        />
      );

      // Label content
      expect(html).toContain("An interesting soul");

      // Unselected card border and background
      expect(html).toContain("border-transparent");
      expect(html).toContain("bg-white/60");

      // Indicator circle present without checkmark
      expect(html).toContain("data-testid=\"option-indicator\"");
      expect(html).not.toContain("data-testid=\"option-checkmark\"");
    });

    it("renders selected visual state matching Figma baseline", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Face/Body"
          selected={true}
          onClick={() => {}}
        />
      );

      // Label content
      expect(html).toContain("Face/Body");

      // Selected plum purple border (#5c3c4f) and white/80 background
      expect(html).toContain("border-[#5c3c4f]");
      expect(html).toContain("bg-white/80");

      // Indicator circle filled with checkmark icon
      expect(html).toContain("data-testid=\"option-indicator\"");
      expect(html).toContain("data-testid=\"option-checkmark\"");
      expect(html).toContain("<svg");
    });
  });

  describe("Single vs Multi Selection Types (DEV-SPEC §2.1 & §4.2–4.3)", () => {
    it("assigns role='radio' for single-choice questions", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Male"
          selected={false}
          selectionType="single"
          onClick={() => {}}
        />
      );

      expect(html).toContain('role="radio"');
      expect(html).toContain('aria-checked="false"');
    });

    it("assigns role='checkbox' for multi-choice questions", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Building a family"
          selected={true}
          selectionType="multi"
          onClick={() => {}}
        />
      );

      expect(html).toContain('role="checkbox"');
      expect(html).toContain('aria-checked="true"');
    });

    it("verifies single and multi share the exact same visual classes", () => {
      const singleHtml = renderToStaticMarkup(
        <OptionCard label="Option 1" selected={true} selectionType="single" onClick={() => {}} />
      );
      const multiHtml = renderToStaticMarkup(
        <OptionCard label="Option 1" selected={true} selectionType="multi" onClick={() => {}} />
      );

      // Both must share the rounded-2xl, border-[#5c3c4f], and checkmark primitive
      expect(singleHtml).toContain("rounded-2xl");
      expect(multiHtml).toContain("rounded-2xl");
      expect(singleHtml).toContain("border-[#5c3c4f]");
      expect(multiHtml).toContain("border-[#5c3c4f]");
      expect(singleHtml).toContain("data-testid=\"option-checkmark\"");
      expect(multiHtml).toContain("data-testid=\"option-checkmark\"");
    });
  });

  describe("Disabled & Interaction Locking (DEV-SPEC §4.2)", () => {
    it("renders disabled state during submission lock while preserving selected visual feedback", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Submitting..."
          selected={true}
          disabled={true}
          onClick={() => {}}
        />
      );

      expect(html).toContain('aria-disabled="true"');
      expect(html).toContain('tabindex="-1"');
      expect(html).toContain("opacity-50");
      expect(html).toContain("pointer-events-none");
      // Preserves selected border and checkmark per DEV-SPEC §4.2 & Audit M-1
      expect(html).toContain("border-[#5c3c4f]");
      expect(html).toContain("data-testid=\"option-checkmark\"");
    });

    it("renders disabled state while preserving error border", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Submitting with error..."
          selected={false}
          hasError={true}
          disabled={true}
          onClick={() => {}}
        />
      );

      expect(html).toContain("opacity-50");
      expect(html).toContain("border-red-400");
    });
  });

  describe("Error State", () => {
    it("renders error highlight when hasError is true", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Required field"
          selected={false}
          hasError={true}
          onClick={() => {}}
        />
      );

      expect(html).toContain("border-red-400");
      expect(html).toContain("bg-red-50/70");
    });
  });

  describe("Mobile Touch Target & Keyboard Usability", () => {
    it("meets mobile touch target standards (>48px min-height)", () => {
      const html = renderToStaticMarkup(
        <OptionCard
          label="Touch target test"
          selected={false}
          onClick={() => {}}
        />
      );

      // Card has min-h-[68px] and p-5 padding
      expect(html).toContain("min-h-[68px]");
      expect(html).toContain("p-5");
      expect(html).toContain('tabindex="0"');
      expect(html).toContain("focus-visible:ring-2");
    });
  });

  describe("RadioGroup Accessible Container & Semantics (M-4)", () => {
    it("renders container with role='radiogroup' and accessible aria-label", () => {
      const html = renderToStaticMarkup(
        <RadioGroup label="What is your gender?" ariaLabelledBy="quiz-title">
          <OptionCard label="Female" selected={true} onClick={() => {}} selectionType="single" />
          <OptionCard label="Male" selected={false} onClick={() => {}} selectionType="single" />
        </RadioGroup>
      );

      expect(html).toContain('role="radiogroup"');
      expect(html).toContain('aria-label="What is your gender?"');
      expect(html).toContain('aria-labelledby="quiz-title"');
      expect(html).toContain('role="radio"');
      expect(html).toContain("data-testid=\"quiz-radiogroup\"");
    });
  });
});
