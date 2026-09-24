"use client";

import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmailCaptureView } from "@/soulmate/components/email";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { SOULMATE_ROUTES } from "@/soulmate/domain";
import {
  getCurrentSession,
  getEmailSummary,
  saveSessionEmail,
  EmailSummaryResponse,
} from "@/soulmate/api/session";

function EmailPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // DEV-SPEC §3, M-3 Audit Remediation: Route Guard for /soulmate/email (Quiz must be completed)
  // In production, Route Guard is strictly enforced; fixture bypass is only allowed in non-production.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture = !isProduction && searchParams.get("fixture") === "true";
  const guardEnabled = isProduction || !isFixture;

  const guard = useRouteGuard({
    targetRoute: "/soulmate/email",
    enabled: guardEnabled,
  });

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

  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [initialEmail, setInitialEmail] = React.useState<string>("");
  const [summaryData, setSummaryData] = React.useState<EmailSummaryResponse | null>(null);

  React.useEffect(() => {
    let isCancelled = false;
    async function loadActiveSession() {
      try {
        const sess = await getCurrentSession();
        if (!isCancelled) {
          setSessionId(sess.session_id);
          if (sess.email) {
            setInitialEmail(sess.email);
          }
        }
        try {
          const summary = await getEmailSummary(sess.session_id);
          if (!isCancelled) {
            setSummaryData(summary);
          }
        } catch {
          // Fallback gracefully to query/sessionStorage params if summary endpoint fails
        }
      } catch {
        // Fallback for static/offline/fixture modes
      }
    }
    loadActiveSession();
    return () => {
      isCancelled = true;
    };
  }, []);

  // Display-ready values from backend view model (SP-302, DEV-SPEC §8.1)
  const effectivePreferredPartnerGender =
    summaryData?.visual_variant || preferredPartnerGender;
  const effectivePartnerAgeRange =
    summaryData?.age_range_display || partnerAgeRange;
  const effectivePartnerEthnicity =
    summaryData?.ethnicity_display || partnerEthnicity;
  const effectiveIsSampleData =
    summaryData !== null ? summaryData.is_sample_data : isSampleData;
  const effectiveUserGender =
    summaryData?.user_gender || userGender;

  const handleSubmit = async (email: string) => {
    // If route guard explicitly denied access, block submission
    if (guardEnabled && guard.allowed === false) {
      return;
    }

    // DEV-SPEC §20 PII Boundary: Email is PII and must never be exposed in URL query parameters.
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem("soulmate_user_email", email);
      } catch {
        // Storage restricted
      }
    }

    let nextRoute: string = SOULMATE_ROUTES.SUBSCRIBE;

    if (sessionId) {
      const res = await saveSessionEmail(sessionId, email);
      if (res && res.next) {
        nextRoute = res.next;
      }
    }

    const params = new URLSearchParams();
    params.set("preferred_partner_gender", effectivePreferredPartnerGender);
    if (effectiveUserGender) params.set("user_gender", effectiveUserGender);
    if (effectivePartnerAgeRange) params.set("age_range", effectivePartnerAgeRange);
    if (effectivePartnerEthnicity) params.set("ethnicity", effectivePartnerEthnicity);

    const query = params.toString();
    router.push(query ? `${nextRoute}?${query}` : nextRoute);
  };

  // Block interaction when route guard check explicitly evaluated to false (M-3 remediation)
  if (guardEnabled && guard.allowed === false) {
    return (
      <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-center p-6 text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center mx-auto text-xl">
          ⚠️
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Quiz Completion Required</h2>
        <p className="text-sm text-neutral-600">
          {guard.verdict?.reason || "Please complete all quiz questions before submitting your email."}
        </p>
        <button
          onClick={() => router.push(guard.verdict?.redirect_to || "/soulmate/quiz")}
          className="w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
        >
          Continue Quiz
        </button>
      </main>
    );
  }

  return (
    <EmailCaptureView
      preferredPartnerGender={effectivePreferredPartnerGender}
      userGender={effectiveUserGender}
      partnerAgeRange={effectivePartnerAgeRange}
      partnerEthnicity={effectivePartnerEthnicity}
      initialEmail={initialEmail}
      isSampleData={effectiveIsSampleData}
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
