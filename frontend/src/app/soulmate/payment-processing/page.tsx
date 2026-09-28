"use client";

import React, { Suspense, useEffect, useState, useRef, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SOULMATE_ROUTES } from "@/soulmate/domain";
import { confirmPayPalSubscription, getSubscriptionStatus } from "@/soulmate/api";
import { trackSoulmateEvent } from "@/soulmate/analytics";

function PaymentProcessingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const subscriptionId = searchParams.get("subscription_id");
  const sessionId = searchParams.get("session_id") || undefined;
  const query = searchParams.toString();
  const resultUrl = `${SOULMATE_ROUTES.RESULT}${query ? `?${query}` : ""}`;

  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [isTerminalState, setIsTerminalState] = useState(false);
  const [terminalMessage, setTerminalMessage] = useState<string | null>(null);
  const [isManualChecking, setIsManualChecking] = useState(false);
  const [manualCheckNote, setManualCheckNote] = useState<string | null>(null);

  const confirmedRef = useRef(false);
  const mountedRef = useRef(false);
  const pollCountRef = useRef(0);
  // §18.1 payment_failed: safe reason categories only (§9.7 — no provider raw
  // error text), each category tracked once per page instance.
  const failedReasonsRef = useRef<Set<string>>(new Set());

  const trackPaymentFailed = useCallback((reasonCode: string) => {
    if (failedReasonsRef.current.has(reasonCode)) return;
    failedReasonsRef.current.add(reasonCode);
    trackSoulmateEvent({ name: "soulmate_payment_failed", properties: { reason_code: reasonCode } });
  }, []);

  useEffect(() => {
    if (!subscriptionId) {
      trackPaymentFailed("missing_subscription_id");
    }
  }, []);

  // 1. Initial Confirmation Request (DEV-SPEC §9.3, §15.7, SP-403)
  // StrictMode-safe (live E2E 2026-09-26): a component-level mount ref re-armed by every
  // effect run, so the async confirm response is not silently discarded when React dev-mode
  // unmount/remount races the in-flight request (the old effect-closure `isMounted` left the
  // component in isPolling=false forever: zero status polls, guaranteed 60s timeout UI).
  useEffect(() => {
    mountedRef.current = true;
    if (!subscriptionId || confirmedRef.current) return;
    const activeSubId = subscriptionId;

    confirmedRef.current = true;

    async function performConfirmation(idToConfirm: string) {
      try {
        const resp = await confirmPayPalSubscription({
          session_id: sessionId,
          paypal_subscription_id: idToConfirm,
        });
        if (mountedRef.current) {
          setIsConfirmed(true);
          // If already paid at confirmation time, navigate immediately (PAY-AUTH-01)
          if (resp.is_paid) {
            router.push(resultUrl);
            return;
          }
          setIsPolling(true);
        }
      } catch (err: unknown) {
        if (mountedRef.current) {
          const msg = err instanceof Error ? err.message : "Failed to confirm subscription with server.";
          setConfirmError(msg);
          trackPaymentFailed("confirmation_failed");
          // Still allow polling in case server recorded the subscription asynchronously
          setIsPolling(true);
        }
      }
    }

    performConfirmation(activeSubId);

    return () => {
      mountedRef.current = false;
    };
  }, [subscriptionId, sessionId, resultUrl, router]);

  // 2. Polling Loop for Server Entitlement Status (DEV-SPEC §15.8, SP-410, PAY-AUTH-01)
  useEffect(() => {
    if (!isPolling || isTerminalState) return;

    let isMounted = true;

    // Check status every 2.5 seconds (DEV-SPEC §15.8: 2–3s)
    const interval = setInterval(async () => {
      pollCountRef.current += 1;
      // After 3 polls (~7.5s) without webhook arrival, trigger live REST API reconciliation (SP-408)
      const shouldReconcile = pollCountRef.current >= 3;

      try {
        const res = await getSubscriptionStatus(sessionId, shouldReconcile);
        if (!isMounted) return;

        // Terminal state detection (e.g. cancelled/expired/suspended during checkout)
        if (res.status === "CANCELLED" || res.status === "SUSPENDED" || res.status === "EXPIRED") {
          clearInterval(interval);
          setIsPolling(false);
          setIsTerminalState(true);
          setTerminalMessage(`Subscription status is ${res.status}. Payment could not be confirmed.`);
          trackPaymentFailed(res.status.toLowerCase());
          return;
        }

        // HIGH-RISK INVARIANT (PAY-AUTH-01):
        // Only navigate to result dashboard when server confirms is_paid === true.
        if (res.is_paid) {
          clearInterval(interval);
          setIsPolling(false);
          router.push(resultUrl);
        }
      } catch {
        // Ignore transient poll errors during processing
      }
    }, 2500);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isPolling, isTerminalState, sessionId, resultUrl, router]);

  // 3. Elapsed Timer for 60s timeout handling (DEV-SPEC §15.8)
  useEffect(() => {
    if (isTerminalState) return;

    const timer = setInterval(() => {
      setElapsedSeconds((prev) => {
        const next = prev + 1;
        // Stop polling after 60 seconds (DEV-SPEC §15.8)
        if (next >= 60) {
          setIsPolling(false);
        }
        return next;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isTerminalState]);

  // §18.1: the 60s wall without server confirmation is a funnel failure too.
  const timeoutTrackedRef = useRef(false);
  useEffect(() => {
    if (elapsedSeconds >= 60 && !isTerminalState && !timeoutTrackedRef.current) {
      timeoutTrackedRef.current = true;
      trackPaymentFailed("confirmation_timeout");
    }
  }, [elapsedSeconds, isTerminalState, trackPaymentFailed]);

  // Manual re-check action for recoverability (Acceptance #3)
  const handleManualRecheck = useCallback(async () => {
    setIsManualChecking(true);
    setManualCheckNote(null);
    try {
      const res = await getSubscriptionStatus(sessionId, true);
      if (res.is_paid) {
        router.push(resultUrl);
        return;
      }
      if (res.status === "CANCELLED" || res.status === "SUSPENDED" || res.status === "EXPIRED") {
        setIsTerminalState(true);
        setTerminalMessage(`Subscription status is ${res.status}. Payment could not be completed.`);
        return;
      }
      setManualCheckNote("Payment is still being processed with PayPal. Please try again in a moment, or check your email for confirmation.");
    } catch {
      setManualCheckNote("Unable to reach payment verification service. Please verify your internet connection or try again.");
    } finally {
      setIsManualChecking(false);
    }
  }, [sessionId, resultUrl, router]);

  const isTakingLonger = elapsedSeconds >= 15;
  const isTimeout = elapsedSeconds >= 60;

  return (
    <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
      <header className="w-full flex justify-between items-center py-4">
        <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
      </header>

      <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-5 my-auto">
        {/* Animated spinner or status icon */}
        {!isTerminalState ? (
          <div className="relative w-16 h-16 mx-auto flex items-center justify-center">
            <div className="w-16 h-16 rounded-full border-4 border-purple-200 border-t-purple-600 animate-spin" />
            <span className="absolute text-xl">⏳</span>
          </div>
        ) : (
          <div className="w-16 h-16 mx-auto flex items-center justify-center rounded-full bg-rose-100 text-rose-600 text-2xl border border-rose-200">
            ⚠️
          </div>
        )}

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-neutral-900" data-testid="processing-title">
            {isTerminalState ? "Payment Could Not Be Confirmed" : isTimeout ? "Confirmation Pending" : "Confirming Payment"}
          </h2>
          <p className="text-xs text-neutral-600 leading-relaxed" data-testid="processing-description">
            {isTerminalState
              ? terminalMessage || "Your transaction was cancelled or declined."
              : isTimeout
              ? "Payment confirmation is taking longer than expected. Do not submit another payment."
              : "We are securely verifying your PayPal subscription. Please do not close or refresh this window."}
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
        {isTakingLonger && !isTimeout && !isTerminalState && (
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

        {/* Final timeout notice at 60s (DEV-SPEC §15.8, SP-410 Acceptance #3) */}
        {isTimeout && !isTerminalState && (
          <div
            data-testid="processing-max-timeout-notice"
            className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 text-left space-y-2"
          >
            <p className="font-semibold text-amber-950">Payment confirmation is taking longer than expected</p>
            <p className="text-[11px] text-amber-800 leading-relaxed">
              PayPal is still confirming your initial payment. Please do not create another subscription. You will receive an email confirmation once your access is unlocked.
            </p>
            <div className="pt-1">
              <button
                type="button"
                data-testid="manual-recheck-btn"
                onClick={handleManualRecheck}
                disabled={isManualChecking}
                className="w-full py-2 px-3 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-50"
              >
                {isManualChecking ? "Checking PayPal Status..." : "Check Status Again"}
              </button>
            </div>
          </div>
        )}

        {manualCheckNote && (
          <div
            data-testid="manual-check-note"
            className="p-2.5 bg-neutral-100 border border-neutral-200 rounded-xl text-[11px] text-neutral-700 text-left"
          >
            {manualCheckNote}
          </div>
        )}

        {confirmError && !isTerminalState && (
          <div
            data-testid="processing-confirm-error"
            className="p-2.5 bg-red-50 border border-red-200 rounded-xl text-[11px] text-red-700 text-left"
          >
            Note: {confirmError}
          </div>
        )}

        {/* Invariant note (PAY-AUTH-01): Entitlement cannot be granted client-side */}
        <div className="pt-2 text-[11px] text-neutral-400">
          <p>Results dashboard unlocks upon server-verified payment completion.</p>
        </div>

        {/* Navigation fallback for missing subscription or terminal failure */}
        {(!subscriptionId || isTerminalState) && (
          <button
            type="button"
            data-testid="return-subscribe-btn"
            onClick={() => router.push(SOULMATE_ROUTES.SUBSCRIBE)}
            className="w-full py-2.5 px-4 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-semibold transition-colors"
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
