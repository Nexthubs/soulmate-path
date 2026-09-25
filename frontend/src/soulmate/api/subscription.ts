/**
 * Soulmate Subscription API Client (DEV-SPEC §9.1–9.4, §15.6–15.8, §21–22, SP-303, SP-403, Decisions: PAY-01, PAY-02, PAY-AUTH-01).
 * Exposes dynamic pricing offer, PayPal subscription confirmation, and status polling without hardcoding.
 */

import { clientConfig, ClientConfig } from "../config";
import { parseApiError } from "./errors";

export interface RenewalDisclosure {
  today_text: string;
  renewal_text: string;
  terms_text: string;
  interval: string;
  interval_count: number;
  auto_renew: boolean;
}

export interface OfferEligibility {
  eligible_for_intro: boolean;
  plan_class: string;
  policy: string;
  is_blocked: boolean;
  reason?: string | null;
}

export interface PayPalClientConfig {
  client_id?: string | null;
  env: string;
  plan_id?: string | null;
}

export interface SubscriptionOfferResponse {
  currency: string;
  intro_price?: string | null;
  regular_price?: string | null;
  interval: string;
  paypal_plan_id?: string | null;
  disclosure: RenewalDisclosure;
  eligibility: OfferEligibility;
  paypal: PayPalClientConfig;
}

export interface PayPalConfirmPayload {
  session_id?: string;
  paypal_subscription_id: string;
}

export interface PayPalConfirmResponse {
  status: string;
  is_paid: boolean;
  provider_subscription_id: string;
  provider_plan_id: string;
  provider_status: string;
  session_id: string;
  created_at: string;
  message: string;
}

export interface SubscriptionStatusResponse {
  status: string;
  is_paid: boolean;
  subscription_id?: string | null;
  plan_id?: string | null;
  provider_status?: string | null;
  first_payment_at?: string | null;
  next_billing_at?: string | null;
  paid_through_at?: string | null;
  cancelled_at?: string | null;
}

/**
 * Fetch the active subscription offer and checkout configuration from the API.
 * Never hardcodes prices; dynamically reads server-configured values (PAY-01).
 * Supports optional session ID to evaluate re-subscription eligibility (PAY-02).
 */
export async function getSubscriptionOffer(
  sessionId?: string,
  config: ClientConfig = clientConfig
): Promise<SubscriptionOfferResponse> {
  const queryParam = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const url = `${config.apiBaseUrl}/subscription/offer${queryParam}`;

  const res = await fetch(url, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
    credentials: "include", // Forward session cookie if present
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}

/**
 * Confirm and associate an approved PayPal subscription with the current session (DEV-SPEC §15.7, SP-403).
 * Validates the provider subscription ID server-side and binds it to the session.
 * HIGH-RISK INVARIANT (PAY-AUTH-01): Returns pending status; does not grant entitlement.
 */
export async function confirmPayPalSubscription(
  payload: PayPalConfirmPayload,
  config: ClientConfig = clientConfig
): Promise<PayPalConfirmResponse> {
  const url = `${config.apiBaseUrl}/subscription/paypal/confirm`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    credentials: "include",
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}

/**
 * Poll current subscription and payment status for the session (DEV-SPEC §15.8, SP-403, SP-408, SP-410).
 * Used by payment-processing screen to detect webhook payment reconciliation.
 * When `reconcile: true`, triggers authoritative PayPal REST API check on the backend.
 */
export async function getSubscriptionStatus(
  sessionId?: string,
  reconcile?: boolean,
  config: ClientConfig = clientConfig
): Promise<SubscriptionStatusResponse> {
  const params = new URLSearchParams();
  if (sessionId) params.append("session_id", sessionId);
  if (reconcile) params.append("reconcile", "true");
  const queryParam = params.toString() ? `?${params.toString()}` : "";
  const url = `${config.apiBaseUrl}/subscription/status${queryParam}`;

  const res = await fetch(url, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
    credentials: "include",
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}

export interface SubscriptionCancelPayload {
  session_id?: string;
  reason?: string;
}

export interface SubscriptionCancelResponse {
  status: string;
  is_paid: boolean;
  subscription_id: string;
  provider_status: string;
  cancelled_at: string;
  paid_through_at?: string | null;
  message: string;
}

/**
 * Cancel the active subscription (DEV-SPEC §9.8, §15.9, SP-409).
 * Idempotent, uses server-side provider API, preserves access until paid_through_at,
 * and permanently retains previously generated artifacts.
 */
export async function cancelSubscription(
  payload?: SubscriptionCancelPayload,
  config: ClientConfig = clientConfig
): Promise<SubscriptionCancelResponse> {
  const url = `${config.apiBaseUrl}/subscription/cancel`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    credentials: "include",
    body: payload ? JSON.stringify(payload) : JSON.stringify({}),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw parseApiError(res.status, errorData);
  }

  return res.json();
}

