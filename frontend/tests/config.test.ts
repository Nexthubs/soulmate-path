import React from "react";
import { describe, it, expect } from "vitest";
import {
  clientConfig,
  validateClientConfig,
  assertClientConfig,
  ClientConfig,
} from "../src/soulmate/config";
import { ConfigValidator } from "../src/soulmate/components/ConfigValidator";
import SoulmateLayout from "../src/app/soulmate/layout";
import SoulmateError from "../src/app/soulmate/error";

describe("Frontend Client Configuration (SP-004)", () => {
  it("exposes centralized client configuration matching contracts", () => {
    expect(clientConfig.appBaseUrl).toBeDefined();
    expect(clientConfig.apiBaseUrl).toBeDefined();
    expect(clientConfig.currency).toBe("USD");
    expect(clientConfig.introPrice).toBeNull();
    expect(clientConfig.regularPrice).toBeNull();
  });

  it("does not have hardcoded production domains in defaults", () => {
    expect(clientConfig.appBaseUrl).not.toContain("stella.love");
    expect(clientConfig.appBaseUrl).not.toContain("stell.love");
  });

  it("passes validation in development mode with defaults", () => {
    const errors = validateClientConfig(clientConfig, "development");
    expect(errors).toHaveLength(0);
    expect(() => assertClientConfig(clientConfig, "development")).not.toThrow();
  });

  it("fails validation in production mode when critical keys are missing or localhost (M-2)", () => {
    const errors = validateClientConfig(clientConfig, "production");
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => e.includes("NEXT_PUBLIC_APP_BASE_URL"))).toBe(true);
    expect(errors.some((e) => e.includes("NEXT_PUBLIC_API_BASE_URL"))).toBe(true);
    expect(errors.some((e) => e.includes("NEXT_PUBLIC_PAYPAL_CLIENT_ID"))).toBe(true);
    expect(errors.some((e) => e.includes("NEXT_PUBLIC_SOULMATE_INTRO_PRICE"))).toBe(true);
    expect(errors.some((e) => e.includes("NEXT_PUBLIC_SOULMATE_REGULAR_PRICE"))).toBe(true);

    expect(() => assertClientConfig(clientConfig, "production")).toThrow(
      /Production client configuration validation failed/
    );
  });

  it("passes validation in production mode when all required keys are valid", () => {
    const validProdConfig: ClientConfig = {
      appBaseUrl: "https://soulmate.example.com",
      apiBaseUrl: "https://api.soulmate.example.com/api/soulmate",
      paypalClientId: "prod_client_id_123",
      currency: "USD",
      introPrice: "19.00",
      regularPrice: "29.00",
    };

    const errors = validateClientConfig(validProdConfig, "production");
    expect(errors).toHaveLength(0);
    expect(() => assertClientConfig(validProdConfig, "production")).not.toThrow();
  });

  it("ConfigValidator component executes validation in browser environment", () => {
    expect(typeof ConfigValidator).toBe("function");
    expect(ConfigValidator()).toBeNull();

    // Emulate browser environment with production NODE_ENV
    const envObj = process.env as Record<string, string | undefined>;
    const origEnv = envObj["NODE_ENV"];
    const globalObj = globalThis as unknown as Record<string, unknown>;
    globalObj["window"] = {};
    try {
      envObj["NODE_ENV"] = "production";
      expect(() => ConfigValidator()).toThrow(/Production client configuration validation failed/);
    } finally {
      envObj["NODE_ENV"] = origEnv;
      delete globalObj["window"];
    }
  });

  it("SoulmateLayout executes server-side assertion in production runtime (not in build phase)", () => {
    const envObj = process.env as Record<string, string | undefined>;
    const origEnv = envObj["NODE_ENV"];
    const origPhase = envObj["NEXT_PHASE"];
    try {
      envObj["NODE_ENV"] = "production";
      delete envObj["NEXT_PHASE"];
      expect(() => SoulmateLayout({ children: null })).toThrow(/Production client configuration validation failed/);

      // In build phase, static page prerendering must pass without throwing
      envObj["NEXT_PHASE"] = "phase-production-build";
      expect(() => SoulmateLayout({ children: null })).not.toThrow();
    } finally {
      envObj["NODE_ENV"] = origEnv;
      if (origPhase !== undefined) {
        envObj["NEXT_PHASE"] = origPhase;
      } else {
        delete envObj["NEXT_PHASE"];
      }
    }
  });

  it("SoulmateError component renders user-facing error state with retry action", () => {
    const mockReset = () => {};
    const configError = new Error("Production client configuration validation failed:\n  - NEXT_PUBLIC_PAYPAL_CLIENT_ID is required");
    const element = SoulmateError({ error: configError, reset: mockReset });
    expect(element).toBeDefined();
    expect(React.isValidElement(element)).toBe(true);
    expect(element.type).toBe("div");
  });
});

