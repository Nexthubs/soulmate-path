"use client";

import { assertClientConfig } from "../config";

/**
 * Client-side component to validate frontend configuration in production mode (SP-004).
 * Runs in the browser runtime to fail fast if required production keys are missing,
 * without breaking static site generation (SSG) prerendering.
 */
export function ConfigValidator() {
  if (typeof window !== "undefined") {
    assertClientConfig();
  }
  return null;
}
