/**
 * Soulmate Path Frontend Configuration (DEV-SPEC §22, Decisions: DOMAIN-01, PAY-01).
 * Reads NEXT_PUBLIC_* environment variables with safe development defaults.
 */

export interface ClientConfig {
  appBaseUrl: string;
  apiBaseUrl: string;
  paypalClientId: string;
  currency: string;
  introPrice: string;
  regularPrice: string;
}

export const clientConfig: ClientConfig = {
  appBaseUrl: process.env.NEXT_PUBLIC_APP_BASE_URL || "http://localhost:3000",
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/soulmate",
  paypalClientId: process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || "",
  currency: process.env.NEXT_PUBLIC_SOULMATE_CURRENCY || "USD",
  introPrice: process.env.NEXT_PUBLIC_SOULMATE_INTRO_PRICE || "19.00",
  regularPrice: process.env.NEXT_PUBLIC_SOULMATE_REGULAR_PRICE || "29.00",
};
