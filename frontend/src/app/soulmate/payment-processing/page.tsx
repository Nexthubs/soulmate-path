"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function PaymentProcessingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const subscriptionId = searchParams.get("subscription_id");
  const sessionId = searchParams.get("session_id");

  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Timer to track how long confirmation is taking (DEV-SPEC §15.8)
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  const isTakingLonger = elapsedSeconds >= 15;

  return (
    <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
      <header className="w-full flex justify-between items-center py-4">
        <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
      </header>

      <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-5 my-auto">
        {/* Animated spinner */}
        <div className="relative w-16 h-16 mx-auto flex items-center justify-center">
          <div className="w-16 h-16 rounded-full border-4 border-purple-200 border-t-purple-600 animate-spin" />
          <span className="absolute text-xl">⏳</span>
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-neutral-900" data-testid="processing-title">
            Confirming Payment
          </h2>
          <p className="text-xs text-neutral-600 leading-relaxed" data-testid="processing-description">
            We are securely verifying your PayPal subscription. Please do not close or refresh this window.
          </p>
        </div>

        {subscriptionId ? (
          <div
            data-testid="processing-subscription-badge"
            className="bg-neutral-50/90 rounded-xl p-3 border border-neutral-200/60 text-left space-y-1"
          >
            <div className="text-[10px] uppercase font-semibold text-neutral-400">Subscription Reference</div>
            <div className="font-mono text-xs text-neutral-800 break-all select-all font-medium">
              {subscriptionId}
            </div>
          </div>
        ) : (
          <div
            data-testid="processing-missing-subscription"
            className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 text-left"
          >
            ⚠️ No active subscription ID was found. If you have not completed checkout, please return to the subscription page.
          </div>
        )}

        {/* Longer wait notification (DEV-SPEC §15.8) */}
        {isTakingLonger && (
          <div
            data-testid="processing-timeout-notice"
            className="p-3 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-900 text-left space-y-1"
          >
            <p className="font-semibold">Payment confirmation is taking longer than expected.</p>
            <p className="text-[11px] text-blue-700">
              Please do not submit another payment. Your subscription is being processed with PayPal and access will unlock automatically upon confirmation.
            </p>
          </div>
        )}

        {/* Invariant note (PAY-AUTH-01): Entitlement cannot be granted client-side */}
        <div className="pt-2 text-[11px] text-neutral-400">
          <p>Results dashboard unlocks upon server-verified payment completion (PAY-AUTH-01).</p>
        </div>

        {/* Navigation fallback if missing subscription */}
        {!subscriptionId && (
          <button
            type="button"
            data-testid="return-subscribe-btn"
            onClick={() => router.push(SOULMATE_ROUTES.SUBSCRIBE)}
            className="w-full py-2.5 px-4 bg-neutral-100 hover:bg-neutral-200 text-neutral-800 rounded-xl text-xs font-semibold transition-colors"
          >
            Return to Subscription Checkout
          </button>
        )}
      </div>

      <footer className="py-4 text-xs text-neutral-400">
        Hint Soulmate &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}

export default function SoulmatePaymentProcessingPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">Loading...</div>}>
      <PaymentProcessingContent />
    </Suspense>
  );
}
