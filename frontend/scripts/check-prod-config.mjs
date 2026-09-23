#!/usr/bin/env node
/**
 * Frontend Production Deployment / Server Startup Configuration Gate (SP-004).
 * Validates that all mandatory NEXT_PUBLIC_* environment variables are present and secure.
 * Exit 0 on valid production configuration.
 * Exit 1 on missing, insecure, or invalid configuration.
 */

const appBaseUrl = process.env.NEXT_PUBLIC_APP_BASE_URL || "";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const paypalClientId = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || "";
const introPrice = process.env.NEXT_PUBLIC_SOULMATE_INTRO_PRICE || "";
const regularPrice = process.env.NEXT_PUBLIC_SOULMATE_REGULAR_PRICE || "";

const errors = [];

if (!appBaseUrl || !appBaseUrl.startsWith("https://") || appBaseUrl.includes("localhost") || appBaseUrl.includes("127.0.0.1")) {
  errors.push("NEXT_PUBLIC_APP_BASE_URL must be a valid production HTTPS URL (not localhost)");
}
if (!apiBaseUrl || !apiBaseUrl.startsWith("https://") || apiBaseUrl.includes("localhost") || apiBaseUrl.includes("127.0.0.1")) {
  errors.push("NEXT_PUBLIC_API_BASE_URL must be a valid production HTTPS URL (not localhost)");
}
if (!paypalClientId || paypalClientId.trim() === "") {
  errors.push("NEXT_PUBLIC_PAYPAL_CLIENT_ID is required in production");
}
if (!introPrice || introPrice.trim() === "") {
  errors.push("NEXT_PUBLIC_SOULMATE_INTRO_PRICE is mandatory in production (PAY-01)");
}
if (!regularPrice || regularPrice.trim() === "") {
  errors.push("NEXT_PUBLIC_SOULMATE_REGULAR_PRICE is mandatory in production (PAY-01)");
}

if (errors.length > 0) {
  console.error("================================================================================");
  console.error(" [FATAL] Frontend Production Configuration Gate FAILED:");
  for (const err of errors) {
    console.error(`   - ${err}`);
  }
  console.error("================================================================================");
  process.exit(1);
} else {
  console.log("[PROD CONFIG CHECK] PASSED: All mandatory frontend production keys are verified.");
  process.exit(0);
}
