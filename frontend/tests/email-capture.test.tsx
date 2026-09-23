import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  EmailCaptureView,
  formatAgeRange,
  formatEthnicity,
  formatGender,
} from "../src/soulmate/components/email";

describe("SP-105: Email Capture Male/Female Variants (DEV-SPEC §2, §8; QUIZ-01)", () => {
  describe("Single Component Handling Both Male & Female Variants (Acceptance #1)", () => {
    it("renders female variant matching Figma node 102:486", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="female"
          partnerAgeRange="30-40"
          partnerEthnicity="Latino"
        />
      );

      // Verify single component wrapper
      expect(html).toContain("data-testid=\"email-capture-view\"");
      expect(html).toContain("data-variant=\"female\"");

      // Verify female sketch illustration asset
      expect(html).toContain("sketch-female.png");

      // Verify headers
      expect(html).toContain("You&#x27;re one step closer to");
      expect(html).toContain("See your soulmate!");
      expect(html).toContain("Where should we send it?");

      // Verify gender badge says Female
      expect(html).toContain("data-testid=\"summary-gender-value\"");
      expect(html).toContain("Female");
    });

    it("renders male variant matching Figma node 102:557", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="male"
          partnerAgeRange="30-40"
          partnerEthnicity="Latino"
        />
      );

      expect(html).toContain("data-testid=\"email-capture-view\"");
      expect(html).toContain("data-variant=\"male\"");

      // Verify male sketch illustration asset
      expect(html).toContain("sketch-male.png");

      // Verify gender badge says Male
      expect(html).toContain("data-testid=\"summary-gender-value\"");
      expect(html).toContain("Male");
    });
  });

  describe("QUIZ-01 Invariant: Variant Chosen by Q3 (preferred_partner_gender), NOT Q2 (user_gender)", () => {
    it("selects female variant when Q3='female' even if Q2 user_gender='male'", () => {
      // User is male, seeking female soulmate (Q2=male, Q3=female)
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="female"
          userGender="male"
          partnerAgeRange="30-40"
          partnerEthnicity="Latino"
        />
      );

      // Must be female variant because Q3 is female
      expect(html).toContain("data-variant=\"female\"");
      expect(html).toContain("sketch-female.png");
      expect(html).not.toContain("sketch-male.png");

      expect(html).toContain("Female");
    });

    it("selects male variant when Q3='male' even if Q2 user_gender='female'", () => {
      // User is female, seeking male soulmate (Q2=female, Q3=male)
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="male"
          userGender="female"
          partnerAgeRange="30-40"
          partnerEthnicity="Latino"
        />
      );

      // Must be male variant because Q3 is male
      expect(html).toContain("data-variant=\"male\"");
      expect(html).toContain("sketch-male.png");
      expect(html).not.toContain("sketch-female.png");

      expect(html).toContain("Male");
    });

    it("does not alter visual variant when user_gender changes but preferredPartnerGender remains fixed", () => {
      const htmlWithMaleUser = renderToStaticMarkup(
        <EmailCaptureView preferredPartnerGender="female" userGender="male" />
      );
      const htmlWithFemaleUser = renderToStaticMarkup(
        <EmailCaptureView preferredPartnerGender="female" userGender="female" />
      );

      // Both must render female variant
      expect(htmlWithMaleUser).toContain("data-variant=\"female\"");
      expect(htmlWithFemaleUser).toContain("data-variant=\"female\"");
      expect(htmlWithMaleUser).toContain("sketch-female.png");
      expect(htmlWithFemaleUser).toContain("sketch-female.png");
    });
  });

  describe("Summary Badges Rendering (Q3, Q5, Q6 - Acceptance)", () => {
    it("renders formatted Q3 gender, Q5 age range, and Q6 ethnicity", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="female"
          partnerAgeRange="age_30_40"
          partnerEthnicity="hispanic_latino"
        />
      );

      expect(html).toContain("data-testid=\"summary-footer\"");

      // Gender badge
      expect(html).toContain("data-testid=\"summary-item-gender\"");
      expect(html).toContain("Gender");
      expect(html).toContain("Female");

      // Age badge
      expect(html).toContain("data-testid=\"summary-item-age\"");
      expect(html).toContain("Age");
      expect(html).toContain("30-40");

      // Ethnicity badge
      expect(html).toContain("data-testid=\"summary-item-ethnicity\"");
      expect(html).toContain("Ethnicity");
      expect(html).toContain("Latino");
    });

    it("renders custom string values directly if passed", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView
          preferredPartnerGender="male"
          partnerAgeRange="25-35"
          partnerEthnicity="Asian"
        />
      );

      expect(html).toContain("Male");
      expect(html).toContain("25-35");
      expect(html).toContain("Asian");
    });
  });

  describe("Form Inputs, Validation, Error & Submitting States (Acceptance #2)", () => {
    it("renders email input with label, placeholder, and ARIA attributes", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView initialEmail="test@example.com" />
      );

      expect(html).toContain("soulmate-email-input");
      expect(html).toContain("Email");
      expect(html).toContain("value=\"test@example.com\"");
      expect(html).toContain("aria-required=\"true\"");
      expect(html).toContain("placeholder=\"your.email@example.com\"");
    });

    it("renders external error message and highlights input container with red border", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView error="Invalid email address format" />
      );

      expect(html).toContain("data-testid=\"email-error-msg\"");
      expect(html).toContain("Invalid email address format");
      expect(html).toContain("border-red-400");
      expect(html).toContain("aria-invalid=\"true\"");
    });

    it("renders submitting/loading state with disabled button and spinner", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView loading={true} />
      );

      expect(html).toContain("disabled=\"\"");
      expect(html).toContain("Submitting...");
      expect(html).toContain("animate-spin");
    });

    it("renders terms & conditions checkbox in checked state by default", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView termsAcceptedDefault={true} />
      );

      expect(html).toContain("data-testid=\"terms-checkbox\"");
      expect(html).toContain("role=\"checkbox\"");
      expect(html).toContain("aria-checked=\"true\"");
      expect(html).toContain("Terms &amp; Conditions");
      expect(html).toContain("Privacy Notice");
    });

    it("renders terms & conditions checkbox in unchecked state when specified", () => {
      const html = renderToStaticMarkup(
        <EmailCaptureView termsAcceptedDefault={false} />
      );

      expect(html).toContain("data-testid=\"terms-checkbox\"");
      expect(html).toContain("aria-checked=\"false\"");
    });
  });

  describe("Helper Formatters", () => {
    it("formatAgeRange converts code to range string", () => {
      expect(formatAgeRange("age_20_30")).toBe("20-30");
      expect(formatAgeRange("age_30_40")).toBe("30-40");
      expect(formatAgeRange("age_40_50")).toBe("40-50");
      expect(formatAgeRange("age_50_plus")).toBe("50+");
      expect(formatAgeRange("custom_age")).toBe("custom_age");
      expect(formatAgeRange(undefined)).toBe("30-40");
    });

    it("formatEthnicity converts code to ethnicity label", () => {
      expect(formatEthnicity("hispanic_latino")).toBe("Latino");
      expect(formatEthnicity("caucasian_white")).toBe("Caucasian");
      expect(formatEthnicity("african_african_american")).toBe("African");
      expect(formatEthnicity("asian")).toBe("Asian");
      expect(formatEthnicity("no_preference")).toBe("Any");
      expect(formatEthnicity(undefined)).toBe("Latino");
    });

    it("formatGender capitalizes gender properly", () => {
      expect(formatGender("male")).toBe("Male");
      expect(formatGender("female")).toBe("Female");
      expect(formatGender(undefined)).toBe("Female");
    });
  });
});
