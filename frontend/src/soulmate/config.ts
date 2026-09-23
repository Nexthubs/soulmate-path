/**
 * Soulmate Path Frontend Configuration (DEV-SPEC §22, Decisions: DOMAIN-01, PAY-01).
 * Reads NEXT_PUBLIC_* environment variables with safe development defaults.
 */

export interface ClientConfig {
  appBaseUrl: string;
  apiBaseUrl: string;
  paypalClientId: string;
  currency: string;
  introPrice: string | null;
  regularPrice: string | null;
}

export const clientConfig: ClientConfig = {
  appBaseUrl: process.env.NEXT_PUBLIC_APP_BASE_URL || "http://localhost:3000",
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/soulmate",
  paypalClientId: process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || "",
  currency: process.env.NEXT_PUBLIC_SOULMATE_CURRENCY || "USD",
  introPrice: process.env.NEXT_PUBLIC_SOULMATE_INTRO_PRICE || null,
  regularPrice: process.env.NEXT_PUBLIC_SOULMATE_REGULAR_PRICE || null,
};

/**
 * Validates client configuration for production readiness (Fixes M-2).
 * Returns array of validation error messages, or empty array if valid.
 */
export function validateClientConfig(
  config: ClientConfig = clientConfig,
  nodeEnv: string = process.env.NODE_ENV || "development"
): string[] {
  const errors: string[] = [];

  if (nodeEnv.toLowerCase() === "production") {
    if (
      !config.appBaseUrl ||
      !config.appBaseUrl.startsWith("https://") ||
      config.appBaseUrl.includes("localhost") ||
      config.appBaseUrl.includes("127.0.0.1")
    ) {
      errors.push("NEXT_PUBLIC_APP_BASE_URL must be a valid production HTTPS URL (not localhost)");
    }
    if (
      !config.apiBaseUrl ||
      !config.apiBaseUrl.startsWith("https://") ||
      config.apiBaseUrl.includes("localhost") ||
      config.apiBaseUrl.includes("127.0.0.1")
    ) {
      errors.push("NEXT_PUBLIC_API_BASE_URL must be a valid production HTTPS URL (not localhost)");
    }
    if (!config.paypalClientId || config.paypalClientId.trim() === "") {
      errors.push("NEXT_PUBLIC_PAYPAL_CLIENT_ID is required in production");
    }
    if (!config.introPrice || config.introPrice.trim() === "") {
      errors.push("NEXT_PUBLIC_SOULMATE_INTRO_PRICE is mandatory in production (PAY-01)");
    }
    if (!config.regularPrice || config.regularPrice.trim() === "") {
      errors.push("NEXT_PUBLIC_SOULMATE_REGULAR_PRICE is mandatory in production (PAY-01)");
    }
  }

  return errors;
}

/**
 * Asserts client configuration is valid, throwing Error in production if invalid.
 */
export function assertClientConfig(
  config: ClientConfig = clientConfig,
  nodeEnv: string = process.env.NODE_ENV || "development"
): void {
  const errors = validateClientConfig(config, nodeEnv);
  if (errors.length > 0) {
    throw new Error(
      `Production client configuration validation failed:\n  - ${errors.join("\n  - ")}`
    );
  }
}
