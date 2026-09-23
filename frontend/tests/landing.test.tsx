import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SoulmateLandingPage } from "../src/soulmate/components/landing/SoulmateLandingPage";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

describe("SP-101: Soulmate Landing Page Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders canonical 390px design baseline elements matching Figma 102:44", () => {
    const html = renderToStaticMarkup(<SoulmateLandingPage showMarketingClaims={true} />);

    // Brand and Login in TopAppBar
    expect(html).toContain("Hint Soulmate");
    expect(html).toContain("Login");
    expect(html).toContain('href="/login"');

    // Main Headline
    expect(html).toContain("See the Face");
    expect(html).toContain("Soulmate");

    // Central Hero Asset
    expect(decodeURIComponent(html)).toContain("/images/landing/soulmate-hero-illustration.png");

    // Primary CTA
    expect(html).toContain("Let&#x27;s begin");

    // Legal & Compliance Footer
    expect(html).toContain("Terms &amp; Conditions");
    expect(html).toContain("Privacy Notice");
    expect(html).toContain("mailto:support@soulmatepath.com");
    expect(html).toContain("For entertainment purposes only");
  });

  describe("Compliance & Marketing Gate (DEV-SPEC §21 & LEGAL-01)", () => {
    it("omits unverified marketing stats and media claims when showMarketingClaims is false", () => {
      const html = renderToStaticMarkup(<SoulmateLandingPage showMarketingClaims={false} />);

      // Must not render unverified badges or media claims
      expect(html).not.toContain("3M+");
      expect(html).not.toContain("sketches created");
      expect(html).not.toContain("18K+");
      expect(html).not.toContain("5 star reviews");
      expect(html).not.toContain("/images/landing/featured-in.png");
      expect(html).not.toContain("data-testid=\"marketing-badges\"");
      expect(html).not.toContain("data-testid=\"featured-in-media\"");

      // Core product elements must remain intact and functional
      expect(html).toContain("Hint Soulmate");
      expect(html).toContain("See the Face");
      expect(html).toContain("Let&#x27;s begin");
      expect(html).toContain("For entertainment purposes only");
    });

    it("renders marketing stats and media claims when showMarketingClaims is true", () => {
      const html = renderToStaticMarkup(<SoulmateLandingPage showMarketingClaims={true} />);

      expect(html).toContain("3M+");
      expect(html).toContain("sketches created");
      expect(html).toContain("18K+");
      expect(html).toContain("5 star reviews");
      expect(decodeURIComponent(html)).toContain("/images/landing/featured-in.png");
      expect(html).toContain("data-testid=\"marketing-badges\"");
      expect(html).toContain("data-testid=\"featured-in-media\"");
    });
  });

  describe("Keyboard & Accessibility Standards", () => {
    it("has accessible button and link semantics", () => {
      const html = renderToStaticMarkup(<SoulmateLandingPage />);

      // CTA button must have type="button" and accessible aria-label
      expect(html).toContain('type="button"');
      expect(html).toContain('aria-label="Let&#x27;s begin finding your soulmate"');

      // Login link must have accessible aria-label
      expect(html).toContain('aria-label="Log in to existing account"');

      // Images must have non-empty alt text
      expect(html).toContain('alt="Soulmate silhouette preview with compatibility aspect badges"');
    });

    it("allows custom loginUrl and nextRoute props", () => {
      const html = renderToStaticMarkup(
        <SoulmateLandingPage loginUrl="/auth/signin" nextRoute="/soulmate/quiz" />
      );

      expect(html).toContain('href="/auth/signin"');
    });
  });
});
