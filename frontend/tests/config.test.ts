import { describe, it, expect } from "vitest";
import { clientConfig } from "../src/soulmate/config";

describe("Frontend Client Configuration (SP-004)", () => {
  it("exposes centralized client configuration matching contracts", () => {
    expect(clientConfig.appBaseUrl).toBeDefined();
    expect(clientConfig.apiBaseUrl).toBeDefined();
    expect(clientConfig.currency).toBe("USD");
    expect(clientConfig.introPrice).toBe("19.00");
    expect(clientConfig.regularPrice).toBe("29.00");
  });

  it("does not have hardcoded production domains in defaults", () => {
    expect(clientConfig.appBaseUrl).not.toContain("stella.love");
    expect(clientConfig.appBaseUrl).not.toContain("stell.love");
  });
});
