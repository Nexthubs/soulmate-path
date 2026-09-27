"use client";

import React, { useState } from "react";
import { cancelSubscription, SubscriptionCancelResponse } from "../../api/subscription";

export interface SubscriptionSettingsActionProps {
  status: string;
  isPaid: boolean;
  subscriptionId?: string | null;
  planId?: string | null;
  /** Plan currency of the reconciled subscription, e.g. "USD" (SP-803). */
  currency?: string | null;
  /** Regular monthly renewal price, decimal string from backend state (SP-803). */
  regularPrice?: string | null;
  nextBillingAt?: string | null;
  paidThroughAt?: string | null;
  cancelledAt?: string | null;
  sessionId?: string;
  onCancelSuccess?: (response: SubscriptionCancelResponse) => void;
  className?: string;
}

export function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "N/A";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  } catch {
    return dateStr;
  }
}

/**
 * Formats the provider-reconciled regular monthly price for display (SP-803).
 * Returns null when no valid price is available so callers can omit the row
 * instead of fabricating one.
 */
export function formatSubscriptionPrice(
  price?: string | null,
  currency?: string | null
): string | null {
  if (!price) return null;
  const value = Number(price);
  if (!Number.isFinite(value) || value <= 0) return null;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency && currency.length === 3 ? currency : "USD",
      minimumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency ?? "USD"} ${price}`.trim();
  }
}

/**
 * Subscription settings action component (DEV-SPEC §9.8, §15.9, SP-409).
 * Provides clear cancellation confirmation, server-side cancellation call,
 * accurate paid-through access semantics, repeated cancellation safety,
 * and clear messaging that completed sketch/report artifacts are never deleted.
 */
export function SubscriptionSettingsAction({
  status: initialStatus,
  isPaid,
  subscriptionId,
  planId,
  currency,
  regularPrice,
  nextBillingAt: initialNextBilling,
  paidThroughAt: initialPaidThrough,
  cancelledAt: initialCancelledAt,
  sessionId,
  onCancelSuccess,
  className = "",
}: SubscriptionSettingsActionProps) {
  const [status, setStatus] = useState<string>(initialStatus);
  const [paidThrough, setPaidThrough] = useState<string | null | undefined>(initialPaidThrough || initialNextBilling);
  const [cancelledAt, setCancelledAt] = useState<string | null | undefined>(initialCancelledAt);
  const [isConfirming, setIsConfirming] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const isCancelled = status === "CANCELLED" || Boolean(cancelledAt);
  // SP-803: renewal price quoted in the confirmation dialog comes exclusively
  // from provider-reconciled backend state; null omits the price sentence.
  const priceText = formatSubscriptionPrice(regularPrice, currency);

  const handleCancelClick = () => {
    setError(null);
    setIsConfirming(true);
  };

  const handleConfirmCancel = async () => {
    // Safe repeated action (SP-804): ignore re-entry while a request is in
    // flight; the confirm button is also disabled during the request.
    if (isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      const resp = await cancelSubscription({
        session_id: sessionId,
        reason: "Customer requested cancellation via settings",
      });
      setStatus(resp.status);
      if (resp.paid_through_at) {
        setPaidThrough(resp.paid_through_at);
      }
      setCancelledAt(resp.cancelled_at);
      setIsConfirming(false);
      setSuccessMessage(resp.message || "Your subscription has been cancelled. No future renewals will occur.");
      if (onCancelSuccess) {
        onCancelSuccess(resp);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to cancel subscription. Please try again.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      data-testid="subscription-settings-action"
      className={`rounded-2xl border border-rose-100 bg-white/80 p-6 shadow-sm backdrop-blur-sm ${className}`}
    >
      <div className="flex flex-col gap-4">
        {/* Header and status badge */}
        <div className="flex items-center justify-between border-b border-rose-50 pb-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-800">Soulmate Subscription</h3>
            {subscriptionId && (
              <p className="text-xs text-slate-500 font-mono mt-0.5">ID: {subscriptionId}</p>
            )}
          </div>
          <div>
            {isCancelled ? (
              <span
                data-testid="subscription-status-badge"
                className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
              >
                Cancelled
              </span>
            ) : status === "ACTIVE" ? (
              <span
                data-testid="subscription-status-badge"
                className="inline-flex items-center rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 border border-emerald-200"
              >
                Active
              </span>
            ) : (
              <span
                data-testid="subscription-status-badge"
                className="inline-flex items-center rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 border border-amber-200"
              >
                {status || "Pending"}
              </span>
            )}
          </div>
        </div>

        {/* Plan and price — provider-reconciled backend state (SP-803).
            V1 has exactly one monthly plan (DEV-SPEC §9.1); the price comes
            from the backend subscription row, never a frontend constant. */}
        <div className="flex justify-between text-sm text-slate-600" data-testid="subscription-plan-info">
          <span>Plan:</span>
          <span className="font-medium text-slate-800">
            {formatSubscriptionPrice(regularPrice, currency)
              ? `Monthly — ${formatSubscriptionPrice(regularPrice, currency)}/month`
              : "Monthly"}
          </span>
        </div>

        {/* Status messages and dates */}
        <div className="space-y-2 text-sm text-slate-600">
          {!isCancelled && initialNextBilling && (
            <div className="flex justify-between" data-testid="next-billing-info">
              <span>Next Renewal Date:</span>
              <span className="font-medium text-slate-800">{formatDate(initialNextBilling)}</span>
            </div>
          )}

          {isCancelled ? (
            <div className="rounded-xl bg-amber-50/70 p-4 border border-amber-200/60 space-y-2" data-testid="cancelled-access-info">
              <div className="flex items-center justify-between text-amber-900 font-medium">
                <span>Access Status:</span>
                <span data-testid="paid-through-display">
                  {paidThrough ? `Active through ${formatDate(paidThrough)}` : "Access retained"}
                </span>
              </div>
              <p className="text-xs text-amber-800">
                No future renewal charges will be made. You retain full access to all paid features until your current cycle ends.
              </p>
              <div className="pt-2 border-t border-amber-200/50 text-xs text-amber-900 flex items-center gap-1.5" data-testid="artifact-retention-notice">
                <svg className="w-4 h-4 text-emerald-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <span>Your completed Soulmate Sketch and Report are permanently saved and will never be deleted.</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Your subscription renews automatically monthly. You may cancel at any time while retaining access through the end of your billing cycle.
            </p>
          )}

          {successMessage && (
            <div data-testid="success-message" className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-800 border border-emerald-200">
              {successMessage}
            </div>
          )}

          {error && (
            <div data-testid="error-message" className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700 border border-rose-200">
              {error}
            </div>
          )}
        </div>

        {/* Action button */}
        {!isCancelled && (
          <div className="pt-2">
            {!isConfirming ? (
              <button
                type="button"
                data-testid="cancel-subscription-button"
                onClick={handleCancelClick}
                className="text-xs text-rose-600 hover:text-rose-700 hover:underline font-medium focus:outline-none"
              >
                Cancel Subscription
              </button>
            ) : (
              <CancelConfirmationDialog
                paidThroughDisplay={formatDate(paidThrough || initialNextBilling)}
                priceText={priceText}
                isLoading={isLoading}
                onConfirm={handleConfirmCancel}
                onKeep={() => setIsConfirming(false)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export interface CancelConfirmationDialogProps {
  /** Human-readable access-through date shown as the post-cancel access promise. */
  paidThroughDisplay: string;
  /** Formatted renewal price (e.g. "$29.00") or null when the backend provides none. */
  priceText: string | null;
  isLoading: boolean;
  onConfirm: () => void;
  onKeep: () => void;
}

/**
 * Confirmation state for the cancel action (SP-804, DEV-SPEC §9.8, §15.9).
 * Presentational so all safety/messaging criteria are directly renderable in
 * static tests: quotes the renewal price, the paid-through access promise, and
 * the artifact-retention guarantee; both actions disable while in flight.
 */
export function CancelConfirmationDialog({
  paidThroughDisplay,
  priceText,
  isLoading,
  onConfirm,
  onKeep,
}: CancelConfirmationDialogProps) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="Confirm cancellation"
      data-testid="cancellation-confirmation-dialog"
      className="rounded-xl border border-rose-200 bg-rose-50/50 p-4 space-y-3"
    >
      <h4 className="text-sm font-semibold text-rose-950">Confirm Cancellation</h4>
      <p className="text-xs text-slate-600 leading-relaxed">
        {priceText ? (
          <>
            Your plan renews at <strong>{priceText}/month</strong>. Cancelling stops all future
            charges — no refund is issued for the current cycle.{" "}
          </>
        ) : (
          "Are you sure you want to cancel? "
        )}
        You will keep access until <strong>{paidThroughDisplay}</strong>. Your previously generated
        Sketch and Report will <strong>never be deleted</strong>.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="confirm-cancel-button"
          onClick={onConfirm}
          disabled={isLoading}
          aria-busy={isLoading}
          className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 transition disabled:opacity-50"
        >
          {isLoading ? "Cancelling..." : "Confirm Cancellation"}
        </button>
        <button
          type="button"
          data-testid="keep-subscription-button"
          onClick={onKeep}
          disabled={isLoading}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition"
        >
          Keep Subscription
        </button>
      </div>
    </div>
  );
}
