"use client";

import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmailCaptureView } from "@/soulmate/components/email";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function EmailPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Read quiz summary parameters from URL or state
  // STRICT INVARIANT (QUIZ-01): Visual variant is driven by preferred_partner_gender (Q3), not user_gender (Q2).
  const preferredPartnerGender =
    searchParams.get("preferred_partner_gender") ||
    searchParams.get("partner_gender") ||
    "female";

  const userGender = searchParams.get("user_gender") || undefined;
  const partnerAgeRange = searchParams.get("age_range") || "30-40";
  const partnerEthnicity = searchParams.get("ethnicity") || "Latino";

  const handleSubmit = async (email: string) => {
    // DEV-SPEC §20 PII Boundary: Email is PII and must never be exposed in URL query parameters.
    // In Wave 1 fixture mode, store in client session storage.
    // In Wave 2 (SP-201/SP-301), this will call POST /api/soulmate/sessions/:sessionId/email.
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem("soulmate_user_email", email);
      } catch {
        // Storage restricted
      }
    }

    router.push(
      `${SOULMATE_ROUTES.RESULT}?preferred_partner_gender=${encodeURIComponent(
        preferredPartnerGender
      )}`
    );
  };

  return (
    <EmailCaptureView
      preferredPartnerGender={preferredPartnerGender}
      userGender={userGender}
      partnerAgeRange={partnerAgeRange}
      partnerEthnicity={partnerEthnicity}
      onSubmit={handleSubmit}
    />
  );
}

export default function SoulmateEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen text-neutral-400">
          Loading...
        </div>
      }
    >
      <EmailPageContent />
    </Suspense>
  );
}
