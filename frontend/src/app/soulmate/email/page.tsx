"use client";

import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmailCaptureView } from "@/soulmate/components/email";

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
    // In production, persists email to session via POST /api/soulmate/sessions/:sessionId/email
    // Navigate to /soulmate/subscribe upon successful email capture (DEV-SPEC §8.2)
    router.push(
      `/soulmate/subscribe?preferred_partner_gender=${encodeURIComponent(
        preferredPartnerGender
      )}&email=${encodeURIComponent(email)}`
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
