"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { getSubscriptionOffer, SubscriptionOfferResponse } from "@/soulmate/api";
import { useRouteGuard } from "@/soulmate/hooks/useRouteGuard";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function SubscribeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  const resultUrl = `${SOULMATE_ROUTES.RESULT}${query ? `?${query}` : ""}`;
  const sessionId = searchParams.get("session_id") || undefined;

  // DEV-SPEC §3, M-3 Audit Remediation: Route Guard for /soulmate/subscribe (Email must be captured)
  // In production, Route Guard is strictly enforced; fixture bypass is only allowed in non-production.
  const isProduction = process.env.NODE_ENV === "production";
  const isFixture = !isProduction && searchParams.get("fixture") === "true";
  const guardEnabled = isProduction || !isFixture;

  const guard = useRouteGuard({
    targetRoute: "/soulmate/subscribe",
    sessionId,
    enabled: guardEnabled,
  });

  const [offer, setOffer] = useState<SubscriptionOfferResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadOffer() {
      try {
        setLoading(true);
        const data = await getSubscriptionOffer(sessionId);
        if (isMounted) {
          setOffer(data);
          setError(null);
        }
      } catch (err: unknown) {
        if (isMounted) {
          // Graceful fallback for offline / mock testing
          setError(err instanceof Error ? err.message : "Failed to load offer");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    loadOffer();

    return () => {
      isMounted = false;
    };
  }, [sessionId]);

  // Block interaction when route guard check explicitly evaluated to false (M-3 remediation)
  if (guardEnabled && guard.allowed === false) {
    return (
      <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-center p-6 text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center mx-auto text-xl">
          ⚠️
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Email Submission Required</h2>
        <p className="text-sm text-neutral-600">
          {guard.verdict?.reason || "Please submit your email before proceeding to subscription checkout."}
        </p>
        <button
          onClick={() => router.push(guard.verdict?.redirect_to || "/soulmate/email")}
          className="w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
        >
          Go to Email Step
        </button>
      </main>
    );
  }

  return (
    <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
      <header className="w-full flex justify-between items-center py-4">
        <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
      </header>

      <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
        <div className="w-12 h-12 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center mx-auto text-xl">
          💳
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Subscription Checkout</h2>

        {loading ? (
          <div data-testid="offer-loading" className="py-6 text-sm text-neutral-500 animate-pulse">
            Loading checkout offer...
          </div>
        ) : offer ? (
          <div data-testid="offer-details" className="space-y-4 text-left pt-2">
            {/* Eligibility Banner (PAY-02) */}
            {offer.eligibility.is_blocked ? (
              <div
                data-testid="eligibility-blocked-banner"
                className="p-3 bg-amber-50 border border-amber-200 text-amber-900 rounded-xl text-xs leading-relaxed"
              >
                ⚠️ {offer.eligibility.reason || "Re-subscription currently restricted."}
              </div>
            ) : offer.eligibility.eligible_for_intro ? (
              <div
                data-testid="eligibility-intro-badge"
                className="inline-block px-3 py-1 bg-purple-100 text-purple-700 font-semibold rounded-full text-xs"
              >
                ✨ Special Introductory Offer
              </div>
            ) : (
              <div
                data-testid="eligibility-standard-badge"
                className="inline-block px-3 py-1 bg-neutral-100 text-neutral-700 font-semibold rounded-full text-xs"
              >
                Standard Subscription
              </div>
            )}

            {/* Dynamic Price Presentation (DEV-SPEC §9.1, §21, Decisions: PAY-01) */}
            <div className="bg-neutral-50/80 rounded-2xl p-4 border border-neutral-200/60 space-y-2">
              <div className="flex justify-between items-baseline">
                <span className="text-xs uppercase tracking-wide text-neutral-500 font-medium">First Month</span>
                <span data-testid="today-price-text" className="text-xl font-bold text-neutral-900">
                  {offer.disclosure.today_text}
                </span>
              </div>
              <div className="flex justify-between items-baseline pt-1 border-t border-neutral-200/40">
                <span className="text-xs text-neutral-500">Recurring</span>
                <span data-testid="renewal-price-text" className="text-sm font-semibold text-neutral-700">
                  {offer.disclosure.renewal_text}
                </span>
              </div>
            </div>

            {/* Statutory Auto-Renewal Disclosure (DEV-SPEC §21) */}
            <p data-testid="renewal-terms-text" className="text-xs text-neutral-500 leading-relaxed text-center">
              {offer.disclosure.terms_text}
            </p>
          </div>
        ) : (
          <div data-testid="offer-fallback" className="py-2 space-y-2">
            <p className="text-sm text-neutral-600 leading-relaxed">
              PayPal monthly subscription checkout will be integrated in Wave 4 (SP-401/SP-402).
            </p>
            {error && (
              <p className="text-xs text-neutral-400 italic">
                Note: {error}
              </p>
            )}
          </div>
        )}

        {/* DEV-SPEC §3, §9.1, H-2 remediation: Block unentitled navigation to result dashboard */}
        {guard.verdict?.is_paid ? (
          <Link
            href={resultUrl}
            data-testid="subscribe-result-link"
            className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors text-center"
          >
            Continue to Result Dashboard
          </Link>
        ) : isFixture ? (
          <Link
            href={resultUrl}
            data-testid="subscribe-fixture-link"
            className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors text-center"
          >
            [Demo Preview] Continue to Result Dashboard
          </Link>
        ) : (
          <div className="space-y-2 pt-2">
            <button
              type="button"
              disabled
              data-testid="subscribe-payment-pending"
              className="w-full py-3 px-4 rounded-xl bg-neutral-200 text-neutral-500 font-semibold text-sm text-center cursor-not-allowed select-none"
            >
              🔒 Complete Payment to Access Results
            </button>
            <p className="text-xs text-neutral-400 text-center">
              Soulmate results dashboard is unlocked after payment confirmation (DEV-SPEC §3, §9.1).
            </p>
          </div>
        )}
      </div>

      <footer className="py-4 text-xs text-neutral-400">
        Hint Soulmate &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}

export default function SoulmateSubscribePage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">Loading...</div>}>
      <SubscribeContent />
    </Suspense>
  );
}
