import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  TransitionShell,
  Transition5Progress,
  InterstitialModal,
  WarningModal,
  INTERSTITIAL_POPUP_SEQUENCE,
  getNextInterstitialPopup,
  getTransition2Copy,
  getTransition3Copy,
  TRANSITION_2_CONFIRMED_COPY,
  TRANSITION_2_FALLBACK_COPY,
  TRANSITION_4_STATIC_COPY,
} from "../src/soulmate/components/transition";

describe("SP-104: Transition Shared Layout + Interstitial Shells", () => {
  describe("TransitionShell (Steps 0–5, Figma 102:245-386)", () => {
    it("renders shell container with correct step testid and 390px mobile layout", () => {
      const html = renderToStaticMarkup(
        <TransitionShell
          step={0}
          title="3 Million+ people have seen their Soulmate"
          onContinue={() => {}}
        >
          <div data-testid="test-child">Testimonial Content</div>
        </TransitionShell>
      );

      expect(html).toContain("data-testid=\"transition-shell-step-0\"");
      expect(html).toContain("max-w-[390px]");
      expect(html).toContain("3 Million+ people have seen their Soulmate");
      expect(html).toContain("data-testid=\"test-child\"");
      expect(html).toContain("Testimonial Content");
      expect(html).toContain("Continue");
    });

    it("renders optional badge when provided (e.g. Step 1 'Sketching now')", () => {
      const badgeNode = (
        <span data-testid="sketching-badge" className="text-purple-600">
          Sketching now
        </span>
      );

      const html = renderToStaticMarkup(
        <TransitionShell
          step={1}
          badge={badgeNode}
          title="Your artist has started"
          onContinue={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"transition-badge\"");
      expect(html).toContain("data-testid=\"sketching-badge\"");
      expect(html).toContain("Sketching now");
      expect(html).toContain("Your artist has started");
    });

    it("renders optional illustration when provided", () => {
      const illustrationNode = (
        <span data-testid="target-illustration">
          Target Icon
        </span>
      );

      const html = renderToStaticMarkup(
        <TransitionShell
          step={2}
          title="Awesome!"
          subtitle="Dynamic subtitle"
          illustration={illustrationNode}
          onContinue={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"transition-illustration\"");
      expect(html).toContain("data-testid=\"target-illustration\"");
      expect(html).toContain("Target Icon");
      expect(html).toContain("Awesome!");
      expect(html).toContain("Dynamic subtitle");
    });

    it("supports custom button label and loading/disabled state", () => {
      const html = renderToStaticMarkup(
        <TransitionShell
          step={5}
          title="Preparing results"
          onContinue={() => {}}
          continueLabel="See Results"
          loading={true}
        />
      );

      expect(html).toContain("disabled=\"\"");
      expect(html).toContain("Loading...");
      expect(html).toContain("aria-label=\"See Results\"");
    });
  });

  describe("Transition5Progress (Experiential Progress Bars, DEV-SPEC §5.7)", () => {
    it("renders the three experiential progress bars with target percentages", () => {
      const html = renderToStaticMarkup(
        <Transition5Progress animated={false} />
      );

      expect(html).toContain("data-testid=\"transition-5-progress\"");
      expect(html).toContain("Preparing Your Personal Soulmate Insights");

      // Verify the 3 specific items from DEV-SPEC §5.7 & Figma 102:386
      expect(html).toContain("Heart’s Intentions");
      expect(html).toContain("100%");

      expect(html).toContain("Portrait of the Soulmate");
      expect(html).toContain("85%");

      expect(html).toContain("Connection Insights");
      expect(html).toContain("0%");
    });

    it("includes proper ARIA progressbar roles and attributes for accessibility", () => {
      const html = renderToStaticMarkup(
        <Transition5Progress animated={false} />
      );

      // Verify accessible progressbar elements
      expect(html).toContain("role=\"progressbar\"");
      expect(html).toContain("aria-valuemin=\"0\"");
      expect(html).toContain("aria-valuemax=\"100\"");
      expect(html).toContain("aria-label=\"Heart’s Intentions\"");
      expect(html).toContain("aria-label=\"Portrait of the Soulmate\"");
      expect(html).toContain("aria-label=\"Connection Insights\"");
    });

    it("allows custom title override", () => {
      const html = renderToStaticMarkup(
        <Transition5Progress
          title="Custom Analysis Header"
          animated={false}
        />
      );

      expect(html).toContain("Custom Analysis Header");
    });
  });

  describe("InterstitialModal & WarningModal (Popups 1–3, DEV-SPEC §5.7)", () => {
    it("returns null when isOpen is false", () => {
      const html = renderToStaticMarkup(
        <InterstitialModal
          type="spiritual"
          isOpen={false}
          onAnswer={() => {}}
        />
      );

      expect(html).toBe("");
    });

    it("renders spiritual popup (Popup-1, Figma 102:425) with accessible dialog semantics", () => {
      const html = renderToStaticMarkup(
        <InterstitialModal
          type="spiritual"
          isOpen={true}
          onAnswer={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"interstitial-modal-spiritual\"");
      expect(html).toContain("role=\"dialog\"");
      expect(html).toContain("aria-modal=\"true\"");
      expect(html).toContain("aria-labelledby=\"interstitial-title\"");
      expect(html).toContain("Do you consider yourself a spiritual person?");
      expect(html).toContain("aria-label=\"No\"");
      expect(html).toContain("aria-label=\"Yes\"");
    });

    it("renders psychic artistry popup (Popup-2, Figma 102:466)", () => {
      const html = renderToStaticMarkup(
        <InterstitialModal
          type="psychic_artistry"
          isOpen={true}
          onAnswer={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"interstitial-modal-psychic_artistry\"");
      expect(html).toContain("Are you familiar with the concept of Psychic Artistry?");
      expect(html).toContain("No");
      expect(html).toContain("Yes");
    });

    it("renders warning popup (Popup-3, Figma 102:445) with warning title and description", () => {
      const html = renderToStaticMarkup(
        <InterstitialModal
          type="warning"
          isOpen={true}
          onAnswer={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"interstitial-modal-warning\"");
      expect(html).toContain("WARNING");
      expect(html).toContain("aria-describedby=\"interstitial-desc\"");
      expect(html).toContain(
        "We have noticed something shocking while searching for your Soulmate. Prepare for surprising results!"
      );
      expect(html).toContain("No");
      expect(html).toContain("Yes");
    });

    it("renders dedicated WarningModal wrapper correctly", () => {
      const html = renderToStaticMarkup(
        <WarningModal
          isOpen={true}
          onAnswer={() => {}}
        />
      );

      expect(html).toContain("data-testid=\"interstitial-modal-warning\"");
      expect(html).toContain("WARNING");
    });

    it("supports custom title and description overrides", () => {
      const html = renderToStaticMarkup(
        <InterstitialModal
          type="warning"
          isOpen={true}
          onAnswer={() => {}}
          customTitle="ATTENTION"
          customDescription="Custom warning notice text"
        />
      );

      expect(html).toContain("ATTENTION");
      expect(html).toContain("Custom warning notice text");
    });

    it("enforces sequential Transition-5 popup order (spiritual -> psychic_artistry -> warning -> null)", () => {
      // DEV-SPEC §5.7 & H-NEW-1: Popups must be sequential without skipping warning
      expect(INTERSTITIAL_POPUP_SEQUENCE).toEqual(["spiritual", "psychic_artistry", "warning"]);

      expect(getNextInterstitialPopup("spiritual")).toBe("psychic_artistry");
      expect(getNextInterstitialPopup("psychic_artistry")).toBe("warning");
      expect(getNextInterstitialPopup("warning")).toBeNull();
    });
  });

  describe("Dynamic Copy Contracts (COPY-02 & COPY-03)", () => {
    it("COPY-02: returns confirmed Figma copy for 'intelligence'", () => {
      const copy = getTransition2Copy("intelligence");
      expect(copy).toBe(
        "Those who seek Intelligence in their soulmate are drawn to meaningful conversations and shared growth."
      );
      expect(TRANSITION_2_CONFIRMED_COPY.intelligence).toBe(copy);
    });

    it("COPY-02: handles case-insensitivity and whitespace", () => {
      expect(getTransition2Copy("  INTELLIGENCE  ")).toBe(
        "Those who seek Intelligence in their soulmate are drawn to meaningful conversations and shared growth."
      );
    });

    it("COPY-02: falls back explicitly without guessing unapproved copy for other options", () => {
      // Unmapped qualities should fall back to neutral placeholder copy per audit fix H-5
      const copyKindness = getTransition2Copy("kindness");
      const copyEmpty = getTransition2Copy(null);

      expect(TRANSITION_2_FALLBACK_COPY).toBe("Your answer will be used to personalize this step.");
      expect(copyKindness).toBe("Your answer will be used to personalize this step.");
      expect(copyEmpty).toBe("Your answer will be used to personalize this step.");
      // Ensure no invented keys exist in confirmed copy
      expect(Object.keys(TRANSITION_2_CONFIRMED_COPY)).toEqual(["intelligence"]);
    });

    it("Transition-3: dynamically derives copy from zodiac and decision style (DEV-SPEC §5.5)", () => {
      const heartResult = getTransition3Copy({ zodiacLabel: "Leo Sun", decisionStyle: "heart" });
      expect(heartResult.zodiacLabel).toBe("Leo Sun");
      expect(heartResult.decisionCopy).toBe("people make decisions using their heart.");
      expect(heartResult.subtitle).toContain("Leo Sun");
      expect(heartResult.subtitle).toContain("using their heart");

      const headResult = getTransition3Copy({ zodiacLabel: "Scorpio Sun", decisionStyle: "head" });
      expect(headResult.decisionCopy).toBe("people make decisions using their head.");

      const bothResult = getTransition3Copy({ zodiacLabel: "Virgo Sun", decisionStyle: "both" });
      expect(bothResult.decisionCopy).toBe("people make decisions using their heart and head.");

      // Default fallback
      const defaultResult = getTransition3Copy(null);
      expect(defaultResult.zodiacLabel).toBe("Your Zodiac");
      expect(defaultResult.decisionCopy).toBe("people make decisions using their heart and head.");
    });

    it("COPY-03: static Figma text is preserved and not invented", () => {
      expect(TRANSITION_4_STATIC_COPY.title).toBe("So many share this challenge");
      expect(TRANSITION_4_STATIC_COPY.subtitle).toBe(
        "Moving on from the past is hard, but so many share this journey. We’ll help you find peace and clarity."
      );
    });
  });
});
