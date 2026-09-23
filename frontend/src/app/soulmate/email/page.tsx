"use client";

import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmailCaptureView } from "@/soulmate/components/email";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function EmailPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Read quiz summary parameters from URL or state (DEV-SPEC §8.1; M-1)
  // STRICT INVARIANT (QUIZ-01): Visual variant is driven by preferred_partner_gender (Q3), not user_gender (Q2).
  const paramPartnerGender =
    searchParams.get("preferred_partner_gender") ||
    searchParams.get("partner_gender");
  const paramAgeRange = searchParams.get("age_range");
  const paramEthnicity = searchParams.get("ethnicity");

  let sessionPartnerGender: string | null = null;
  let sessionAgeRange: string | null = null;
  let sessionEthnicity: string | null = null;

  if (typeof window !== "undefined") {
    try {
      sessionPartnerGender = sessionStorage.getItem("soulmate_q03");
      sessionAgeRange = sessionStorage.getItem("soulmate_q05");
      sessionEthnicity = sessionStorage.getItem("soulmate_q06");
    } catch {
      // storage unavailable
    }
  }

  const preferredPartnerGender =
    paramPartnerGender || sessionPartnerGender || "female";
  const partnerAgeRange = paramAgeRange || sessionAgeRange || "30-40";
  const partnerEthnicity = paramEthnicity || sessionEthnicity || "Latino";

  // If no answer is present from either query params or session storage, mark as sample data
  const isSampleData = !paramPartnerGender && !sessionPartnerGender;

  const userGender = searchParams.get("user_gender") || undefined;

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

    const params = new URLSearchParams();
    params.set("preferred_partner_gender", preferredPartnerGender);
    if (userGender) params.set("user_gender", userGender);
    if (partnerAgeRange) params.set("age_range", partnerAgeRange);
    if (partnerEthnicity) params.set("ethnicity", partnerEthnicity);

    router.push(`${SOULMATE_ROUTES.SUBSCRIBE}?${params.toString()}`);
  };

  return (
    <EmailCaptureView
      preferredPartnerGender={preferredPartnerGender}
      userGender={userGender}
      partnerAgeRange={partnerAgeRange}
      partnerEthnicity={partnerEthnicity}
      isSampleData={isSampleData}
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
