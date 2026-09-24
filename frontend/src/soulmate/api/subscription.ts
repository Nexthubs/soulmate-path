/**
 * Soulmate Subscription API Client (DEV-SPEC §9.1–9.2, §15.6, §21–22, SP-303, Decisions: PAY-01, PAY-02).
 * Exposes dynamic pricing offer, renewal disclosures, and safe PayPal client configuration without hardcoding.
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
