"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { loadScript, PayPalScriptOptions, PayPalNamespace } from "@paypal/paypal-js";

export interface PayPalSubscriptionApprovalData {
  subscriptionID: string;
  orderID?: string;
  facilitatorAccessToken?: string;
}

export interface PayPalSubscriptionButtonProps {
  clientId: string;
  planId: string;
  currency?: string;
  sessionId?: string;
  isBlocked?: boolean;
  disabled?: boolean;
  onApprove: (data: PayPalSubscriptionApprovalData) => void | Promise<void>;
  onCancel?: (data?: unknown) => void;
  onError?: (err?: unknown) => void;
  className?: string;
}

/**
 * PayPal Subscription Button component using PayPal JavaScript SDK (DEV-SPEC §9.3, SP-402).
 * Integrates with PayPal Subscriptions API (vault: true, intent: subscription).
 * Invariant (PAY-AUTH-01): onApprove passes subscriptionID to parent for server verification;
 * never claims payment success or unlocks entitlement client-side.
 */
export function PayPalSubscriptionButton({
  clientId,
  planId,
  currency = "USD",
  sessionId,
  isBlocked = false,
  disabled = false,
  onApprove,
  onCancel,
  onError,
  className = "",
}: PayPalSubscriptionButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState<number>(0);

  const retryLoad = useCallback(() => {
    setLoadAttempt((prev) => prev + 1);
  }, []);

  useEffect(() => {
    // PAY-AUTH-01 invariant: a subscription without custom_id session binding can
    // never be server-confirmed. Refuse to render the checkout (instead of creating
    // an unbindable subscription) when the session identity is missing.
    if (isBlocked || !clientId || !planId || !sessionId) {
      setIsLoading(false);
      if (!isBlocked && clientId && planId && !sessionId) {
        setError("Session binding unavailable — reload the page to continue checkout.");
      }
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    const scriptOptions: PayPalScriptOptions = {
      clientId,
      vault: true,
      intent: "subscription",
      currency: currency || "USD",
    };

    loadScript(scriptOptions)
      .then((paypal: PayPalNamespace | null) => {
        if (!isMounted) return;

        if (!paypal || !paypal.Buttons) {
          throw new Error("PayPal SDK loaded but Buttons component is unavailable.");
        }

        setIsLoading(false);

        // Render PayPal Subscription Buttons. render() is asynchronous: a
        // StrictMode/HMR double-mount can abort an in-flight first render, so the
        // rejection is caught and retried once on a fresh container before being
        // surfaced (review fix: silent unhandled rejection left the checkout blank).
        const renderButtons = async (instance: any) => {
          if (!containerRef.current) return;
          containerRef.current.innerHTML = "";
          await instance.render(containerRef.current);
        };

        const buttonsInstance = paypal.Buttons({
          style: {
            shape: "rect",
            color: "gold",
            layout: "vertical",
            label: "subscribe",
          },
          createSubscription: (_data: unknown, actions: any) => {
            return actions.subscription.create({
              plan_id: planId,
              custom_id: sessionId,
            });
          },
          onApprove: async (data: any) => {
            if (!isMounted) return;
            // HIGH-RISK INVARIANT (PAY-AUTH-01):
            // Only forward subscriptionID for server verification. Never set entitlement here.
            await onApprove({
              subscriptionID: data.subscriptionID,
              orderID: data.orderID,
              facilitatorAccessToken: data.facilitatorAccessToken,
            });
          },
          onCancel: (data: any) => {
            if (!isMounted) return;
            onCancel?.(data);
          },
          onError: (err: any) => {
            if (!isMounted) return;
            onError?.(err);
          },
        });

        renderButtons(buttonsInstance)
          .catch(async (renderErr: unknown) => {
            if (!isMounted) return;
            // One retry after the aborted-render race; the SDK namespace is
            // already loaded, so a fresh container render succeeds.
            await new Promise((resolve) => setTimeout(resolve, 200));
            if (!isMounted) return;
            await renderButtons(buttonsInstance);
          })
          .catch((renderErr: unknown) => {
            if (!isMounted) return;
            const errorMsg =
              renderErr instanceof Error
                ? renderErr.message
                : "Failed to render PayPal checkout buttons.";
            setError(errorMsg);
            onError?.(renderErr);
          });
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        setIsLoading(false);
        const errorMsg = err instanceof Error ? err.message : "Failed to load PayPal checkout SDK.";
        setError(errorMsg);
        onError?.(err);
      });

    return () => {
      isMounted = false;
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
    };
  }, [clientId, planId, currency, sessionId, isBlocked, loadAttempt, onApprove, onCancel, onError]);

  if (isBlocked) {
    return null;
  }

  return (
    <div className={`w-full space-y-2 ${className}`} data-testid="paypal-checkout-wrapper">
      {isLoading && (
        <div
          data-testid="paypal-button-loading"
          className="py-3 text-center text-xs text-neutral-500 animate-pulse flex items-center justify-center space-x-2"
        >
          <div className="w-3.5 h-3.5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
          <span>Loading PayPal checkout...</span>
        </div>
      )}

      {error && (
        <div
          data-testid="paypal-load-error"
          className="p-3 bg-red-50 border border-red-200 text-red-800 rounded-xl text-xs space-y-2 text-center"
        >
          <p className="font-medium">Unable to load PayPal checkout.</p>
          <p className="text-neutral-500 text-[11px]">{error}</p>
          <button
            type="button"
            onClick={retryLoad}
            className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold transition-colors"
          >
            Retry PayPal
          </button>
        </div>
      )}

      <div
        ref={containerRef}
        data-testid="paypal-button-container"
        className={`w-full min-h-[44px] ${disabled ? "opacity-50 pointer-events-none" : ""}`}
      />

      {/* Test helper actions for deterministic unit/integration testing */}
      {process.env.NODE_ENV === "test" && (
        <div data-testid="paypal-test-actions" className="sr-only">
          <button
            type="button"
            data-testid="mock-paypal-approve-btn"
            onClick={() =>
              onApprove({
                subscriptionID: "I-TEST-SUBSCRIPTION-ID",
                orderID: "MOCK-ORDER-123",
              })
            }
          >
            Mock Approve
          </button>
          <button
            type="button"
            data-testid="mock-paypal-cancel-btn"
            onClick={() => onCancel?.({ reason: "user_cancelled" })}
          >
            Mock Cancel
          </button>
          <button
            type="button"
            data-testid="mock-paypal-error-btn"
            onClick={() => onError?.(new Error("Mock PayPal SDK failure"))}
          >
            Mock Error
          </button>
        </div>
      )}
    </div>
  );
}
