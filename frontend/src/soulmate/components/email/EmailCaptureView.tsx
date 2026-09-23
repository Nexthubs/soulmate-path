"use client";

import React, { useState } from "react";
import Image from "next/image";

export interface EmailCaptureViewProps {
  /**
   * Q3: Preferred partner gender ("male" | "female").
   * Governs the sketch illustration and the Gender summary badge.
   * STRICT INVARIANT (QUIZ-01): The visual variant is chosen by Q3, NEVER by Q2.
   */
  preferredPartnerGender?: string;

  /**
   * Q2: User gender.
   * Accepted for session tracking / logging, but MUST NOT determine the visual variant.
   */
  userGender?: string;

  /**
   * Q5: Ideal age range for soulmate (e.g., "30-40" or "age_30_40").
   */
  partnerAgeRange?: string;

  /**
   * Q6: Preferred ethnic background (e.g., "Latino" or "hispanic_latino").
   */
  partnerEthnicity?: string;

  /**
   * Initial email value, if prefilled from session.
   */
  initialEmail?: string;

  /**
   * Terms checkbox initial acceptance state. Defaults to true matching Figma nodes 102:511 & 102:582.
   */
  termsAcceptedDefault?: boolean;

  /**
   * Callback fired on valid form submission with the confirmed email address.
   */
  onSubmit?: (email: string) => Promise<void> | void;

  /**
   * External loading state (e.g. while API call is in-flight).
   */
  loading?: boolean;

  /**
   * External error message override.
   */
  error?: string | null;

  /**
   * Whether the summary values represent fallback sample/demo data rather than user answers (M-1).
   */
  isSampleData?: boolean;

  /**
   * Optional custom container class name.
   */
  className?: string;
}

// Helper to format age range codes to user-friendly labels
export function formatAgeRange(val?: string): string {
  if (!val) return "30-40";
  const map: Record<string, string> = {
    age_20_30: "20-30",
    age_30_40: "30-40",
    age_40_50: "40-50",
    age_50_plus: "50+",
  };
  return map[val.toLowerCase()] || val;
}

// Helper to format ethnicity codes to user-friendly labels
export function formatEthnicity(val?: string): string {
  if (!val) return "Latino";
  const map: Record<string, string> = {
    hispanic_latino: "Latino",
    caucasian_white: "Caucasian",
    african_african_american: "African",
    asian: "Asian",
    no_preference: "Any",
  };
  return map[val.toLowerCase()] || val;
}

// Helper to format gender
export function formatGender(val?: string): string {
  if (!val) return "Female";
  const lower = val.toLowerCase().trim();
  if (lower === "male") return "Male";
  if (lower === "female") return "Female";
  return val.charAt(0).toUpperCase() + val.slice(1);
}

// Basic email regex conforming to standard web validation
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Unified Email Capture Page Component (Figma Nodes 102:486 & 102:557; DEV-SPEC §2, §8; DECISIONS QUIZ-01).
 * Single component supporting both male and female visual variants driven by Q3 (`preferred_partner_gender`).
 */
export function EmailCaptureView({
  preferredPartnerGender = "female",
  userGender, // Intentionally ignored for visual variant per QUIZ-01
  partnerAgeRange = "30-40",
  partnerEthnicity = "Latino",
  initialEmail = "",
  termsAcceptedDefault = true,
  onSubmit,
  loading: externalLoading = false,
  error: externalError = null,
  isSampleData = false,
  className = "",
}: EmailCaptureViewProps) {
  // Normalize preferred partner gender (Q3)
  const isMaleVariant = preferredPartnerGender?.toLowerCase().trim() === "male";
  const partnerGenderLabel = isMaleVariant ? "Male" : "Female";
  const ageLabel = formatAgeRange(partnerAgeRange);
  const ethnicityLabel = formatEthnicity(partnerEthnicity);

  // Form states
  const [email, setEmail] = useState(initialEmail);
  const [termsAccepted, setTermsAccepted] = useState(termsAcceptedDefault);
  const [localError, setLocalError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const displayError = externalError || localError;
  const isLoading = externalLoading || isSubmitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);

    const trimmed = email.trim();
    if (!trimmed) {
      setLocalError("Please enter your email address");
      return;
    }

    if (!EMAIL_REGEX.test(trimmed)) {
      setLocalError("Please enter a valid email address");
      return;
    }

    if (!termsAccepted) {
      setLocalError("You must accept the Terms & Conditions and Privacy Notice to proceed");
      return;
    }

    if (onSubmit) {
      try {
        setIsSubmitting(true);
        await onSubmit(trimmed);
      } catch (err: unknown) {
        setLocalError(err instanceof Error ? err.message : "Failed to submit email. Please try again.");
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  return (
    <div
      data-testid="email-capture-view"
      data-variant={isMaleVariant ? "male" : "female"}
      data-user-gender={userGender}
      data-sample-data={isSampleData ? "true" : "false"}
      className={`relative min-h-screen w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fbfaff] via-[#f7f5fb] to-[#ffffff] overflow-x-hidden flex flex-col justify-between ${className}`}
    >
      {/* Top Background Section & Sketch Preview */}
      <div className="relative w-full pt-12 pb-6 px-6 flex flex-col items-center text-center overflow-hidden">
        {/* Background Sketch Illustration */}
        <div
          className="absolute inset-x-0 top-0 h-[260px] pointer-events-none opacity-40 mix-blend-multiply flex justify-center overflow-hidden"
          aria-hidden="true"
        >
          <Image
            src={isMaleVariant ? "/images/email/sketch-male.png" : "/images/email/sketch-female.png"}
            alt="Soulmate sketch preview"
            width={390}
            height={360}
            className="w-full h-auto object-cover object-top filter blur-[0.3px]"
            priority
            data-testid="sketch-preview-image"
          />
        </div>

        {/* Top Heading 1 (Figma 102:490 / 102:562) */}
        <div className="relative z-10 pt-4 pb-2">
          <h1 className="font-sans font-bold text-[24px] leading-[30px] tracking-tight text-neutral-900">
            You&apos;re one step closer to<br />
            seeing your soulmate<br />
            portrait
          </h1>
        </div>
      </div>

      {/* Main Interaction Card (Figma 102:492 / 102:563) */}
      <div className="relative z-20 w-full bg-white rounded-t-[32px] shadow-2xl px-6 pt-8 pb-10 flex flex-col flex-1 border-t border-neutral-100/60">
        {/* Card Header */}
        <div className="text-center space-y-1 mb-6">
          <p className="font-sans font-bold text-[18px] leading-[26px] text-[#5b2f91]">
            See your soulmate!
          </p>
          <h2 className="font-sans font-bold text-[24px] leading-[32px] text-neutral-900">
            Where should we send it?
          </h2>
        </div>

        {/* Capture Form */}
        <form onSubmit={handleSubmit} noValidate className="space-y-4 w-full">
          {/* Email Input Field */}
          <div className="space-y-1.5">
            <div
              className={`w-full rounded-xl bg-[#f4f5f7] px-4 py-3 border-2 transition-all ${
                displayError
                  ? "border-red-400 bg-red-50/40"
                  : "border-transparent focus-within:border-purple-600 focus-within:bg-white"
              }`}
            >
              <label
                htmlFor="soulmate-email-input"
                className="block text-[12px] font-medium text-neutral-500 leading-tight"
              >
                Email <span className="text-[#5b2f91]">*</span>
              </label>
              <input
                id="soulmate-email-input"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (displayError) setLocalError(null);
                }}
                disabled={isLoading}
                placeholder="your.email@example.com"
                aria-required="true"
                aria-invalid={!!displayError}
                aria-describedby={displayError ? "email-error-msg" : undefined}
                className="w-full bg-transparent text-[15px] font-medium text-neutral-900 placeholder:text-neutral-400 outline-none pt-0.5 disabled:opacity-60 disabled:cursor-not-allowed"
              />
            </div>

            {/* Error Message */}
            {displayError && (
              <p
                id="email-error-msg"
                data-testid="email-error-msg"
                className="text-xs text-red-600 font-medium px-1 flex items-center gap-1 animate-in fade-in duration-200"
              >
                <svg className="w-3.5 h-3.5 fill-current shrink-0" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                    clipRule="evenodd"
                  />
                </svg>
                <span>{displayError}</span>
              </p>
            )}
          </div>

          {/* Submit Button (Figma 102:506 / 102:577) */}
          <button
            type="submit"
            disabled={isLoading}
            data-testid="reveal-portrait-button"
            className="w-full h-[56px] rounded-xl bg-black hover:bg-neutral-800 active:bg-neutral-900 text-white font-sans font-semibold text-[17px] tracking-wide transition-all shadow-md flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 focus-visible:ring-offset-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <span className="inline-flex items-center gap-2">
                <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Submitting...</span>
              </span>
            ) : (
              "Reveal My Portrait"
            )}
          </button>

          {/* Terms & Privacy Checkbox (Figma 102:509 / 102:580) */}
          <div className="pt-2 flex items-start gap-3 px-1 text-left">
            <button
              type="button"
              role="checkbox"
              aria-checked={termsAccepted}
              disabled={isLoading}
              data-testid="terms-checkbox"
              onClick={() => {
                setTermsAccepted(!termsAccepted);
                if (displayError) setLocalError(null);
              }}
              className={`w-5 h-5 rounded-[4px] mt-0.5 flex items-center justify-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 shrink-0 cursor-pointer ${
                termsAccepted ? "bg-[#5b2f91] text-white" : "border-2 border-neutral-300 bg-white"
              }`}
            >
              {termsAccepted && (
                <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
            </button>
            <label
              className="font-sans text-[13px] leading-[19px] text-neutral-600 cursor-pointer select-none"
              onClick={() => {
                if (!isLoading) {
                  setTermsAccepted(!termsAccepted);
                  if (displayError) setLocalError(null);
                }
              }}
            >
              I accept the{" "}
              <a
                href="#terms"
                onClick={(e) => e.stopPropagation()}
                className="text-neutral-900 underline hover:text-purple-700"
              >
                Terms &amp; Conditions
              </a>{" "}
              and{" "}
              <a
                href="#privacy"
                onClick={(e) => e.stopPropagation()}
                className="text-neutral-900 underline hover:text-purple-700"
              >
                Privacy Notice
              </a>
            </label>
          </div>
        </form>

        {/* User Details Footer / Summary Badges (Figma 102:521 / 102:587) */}
        <div
          data-testid="summary-footer"
          className="mt-10 pt-6 border-t border-neutral-100 flex flex-col items-center w-full space-y-3"
        >
          {isSampleData && (
            <span
              data-testid="sample-data-badge"
              className="text-[11px] font-semibold text-amber-800/80 bg-amber-100/70 px-2.5 py-0.5 rounded-full"
            >
              Demo Preview (No Quiz Answers Submitted)
            </span>
          )}
          <div className="flex items-center justify-around text-center w-full">
          {/* Q3 Gender Summary Badge */}
          <div data-testid="summary-item-gender" className="flex flex-col items-center space-y-1">
            <div className="w-12 h-12 rounded-full bg-[#faf5ff] border border-[#f3e8ff] flex items-center justify-center text-[#5b2f91] shadow-xs">
              {isMaleVariant ? (
                // Male Icon (Mars Symbol ♂)
                <svg className="w-6 h-6 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2">
                  <circle cx="10" cy="14" r="5" />
                  <path d="M19 5l-5.4 5.4M19 5h-5M19 5v5" />
                </svg>
              ) : (
                // Female Icon (Venus Symbol ♀)
                <svg className="w-6 h-6 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2">
                  <circle cx="12" cy="9" r="5" />
                  <path d="M12 14v7M9 18h6" />
                </svg>
              )}
            </div>
            <span className="text-[12px] font-medium text-neutral-500">Gender</span>
            <span data-testid="summary-gender-value" className="text-[14px] font-bold text-neutral-900">
              {partnerGenderLabel}
            </span>
          </div>

          {/* Q5 Age Range Summary Badge */}
          <div data-testid="summary-item-age" className="flex flex-col items-center space-y-1">
            <div className="w-12 h-12 rounded-full bg-[#faf5ff] border border-[#f3e8ff] flex items-center justify-center text-[#5b2f91] shadow-xs">
              {/* Person / Age Icon */}
              <svg className="w-6 h-6 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2">
                <circle cx="12" cy="7" r="4" />
                <path d="M5.5 21a6.5 6.5 0 0113 0" />
              </svg>
            </div>
            <span className="text-[12px] font-medium text-neutral-500">Age</span>
            <span data-testid="summary-age-value" className="text-[14px] font-bold text-neutral-900">
              {ageLabel}
            </span>
          </div>

          {/* Q6 Ethnicity Summary Badge */}
          <div data-testid="summary-item-ethnicity" className="flex flex-col items-center space-y-1">
            <div className="w-12 h-12 rounded-full bg-[#faf5ff] border border-[#f3e8ff] flex items-center justify-center text-[#5b2f91] shadow-xs">
              {/* Globe / Ethnicity Icon */}
              <svg className="w-6 h-6 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2">
                <circle cx="12" cy="12" r="9" />
                <path d="M3.6 9h16.8M3.6 15h16.8M12 3a15 15 0 010 18M12 3a15 15 0 000 18" />
              </svg>
            </div>
            <span className="text-[12px] font-medium text-neutral-500">Ethnicity</span>
            <span data-testid="summary-ethnicity-value" className="text-[14px] font-bold text-neutral-900">
              {ethnicityLabel}
            </span>
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
