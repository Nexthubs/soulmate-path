import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SketchViewer, SketchViewState } from "../src/soulmate/components/sketch";
import { SOULMATE_ROUTES } from "../src/soulmate/domain";

// Mock next/navigation
const mockPush = vi.fn();
const mockBack = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: mockBack,
  }),
  useSearchParams: () => ({
    get: (key: string) => (key === "state" ? "completed" : null),
  }),
}));

describe("SP-107: Sketch Viewer Fixture UI (DEV-SPEC §2, §11; DECISIONS ASSET-01, DOMAIN-01)", () => {
  describe("State Rendering Matrix (Acceptance #1)", () => {
    it("renders loading state with progress indicator and aria-busy", () => {
      const html = renderToStaticMarkup(
        <SketchViewer state="loading" />
      );

      expect(html).toContain("data-testid=\"sketch-viewer\"");
      expect(html).toContain("data-state=\"loading\"");
      expect(html).toContain("data-testid=\"sketch-loading-state\"");
      expect(html).toContain("aria-busy=\"true\"");
      expect(html).toContain("Drawing Your Soulmate...");
      expect(html).toContain("Stella&#x27;s artist is hand-crafting your intuitive soulmate pencil portrait");
    });

    it("renders completed state with portrait frame, durableUrl image, and action buttons", () => {
      const testDurableUrl = "https://storage.stella.app/artifacts/soulmate-sketch-user123.png";
      const html = renderToStaticMarkup(
        <SketchViewer
          state="completed"
          durableUrl={testDurableUrl}
        />
      );

      expect(html).toContain("data-testid=\"sketch-viewer\"");
      expect(html).toContain("data-state=\"completed\"");
      expect(html).toContain("data-testid=\"sketch-completed-state\"");
      expect(html).toContain("data-testid=\"sketch-portrait-image\"");
      expect(html).toContain(testDurableUrl);
      expect(html).toContain("data-testid=\"download-sketch-btn\"");
      expect(html).toContain("Save Image");
      expect(html).toContain("data-testid=\"view-report-cta\"");
      expect(html).toContain("View Report");
    });

    it("renders failed state with role=alert, error message, and retry CTA", () => {
      const customError = "Failed to communicate with the artist portrait synthesis engine.";
      const html = renderToStaticMarkup(
        <SketchViewer
          state="failed"
          errorMessage={customError}
        />
      );

      expect(html).toContain("data-testid=\"sketch-viewer\"");
      expect(html).toContain("data-state=\"failed\"");
      expect(html).toContain("data-testid=\"sketch-failed-state\"");
      expect(html).toContain("role=\"alert\"");
      expect(html).toContain("Generation Interrupted");
      expect(html).toContain(customError);
      expect(html).toContain("data-testid=\"sketch-retry-btn\"");
      expect(html).toContain("Retry Generation");
      expect(html).toContain("Back to Dashboard");
    });
  });

  describe("Asset Durability (ASSET-01 / Acceptance #2)", () => {
    it("uses durableUrl directly for image display and download without assuming local paths", () => {
      const remoteS3Url = "https://s3.us-east-1.amazonaws.com/soulmate-artifacts/durable-portrait.webp";
      const html = renderToStaticMarkup(
        <SketchViewer
          state="completed"
          durableUrl={remoteS3Url}
        />
      );

      // Verify the image source is the exact durable URL
      expect(html).toContain(`src="${remoteS3Url}"`);
      // Verify the download link also targets the exact durable URL
      expect(html).toContain(`href="${remoteS3Url}"`);
    });
  });

  describe("Routing & Domain Safety (DOMAIN-01 / Acceptance #3)", () => {
    it("uses SOULMATE_ROUTES.RESULT as default back target without hardcoded domain", () => {
      expect(SOULMATE_ROUTES.RESULT).toBe("/soulmate/result");
      expect(SOULMATE_ROUTES.RESULT).not.toContain("https://");
      expect(SOULMATE_ROUTES.RESULT).not.toContain("stella.love");

      const html = renderToStaticMarkup(
        <SketchViewer />
      );

      expect(html).toContain("data-testid=\"sketch-back-button\"");
      expect(html).toContain("aria-label=\"Go back to previous page\"");
    });
  });

  describe("Figma Fidelity & Card Framing (Figma 102:461 / Acceptance #4)", () => {
    it("renders title 'Your Personal Soulmate Insights' matching Figma 102:462", () => {
      const html = renderToStaticMarkup(
        <SketchViewer />
      );

      expect(html).toContain("Your Personal Soulmate Insights");
    });

    it("renders partner gender badge if provided", () => {
      const html = renderToStaticMarkup(
        <SketchViewer partnerGender="Attracted to Men" />
      );

      expect(html).toContain("Attracted to Men");
    });

    it("renders rounded card framing matching Figma 102:461 style", () => {
      const html = renderToStaticMarkup(
        <SketchViewer state="completed" />
      );

      expect(html).toContain("rounded-[28px]");
      expect(html).toContain("aspect-[3/4]");
    });
  });

  describe("Fixture Toolbar Controls", () => {
    it("renders fixture state selector when showFixtureToolbar is true", () => {
      const html = renderToStaticMarkup(
        <SketchViewer showFixtureToolbar={true} />
      );

      expect(html).toContain("data-testid=\"sketch-fixture-toolbar\"");
      expect(html).toContain("data-testid=\"fixture-tab-loading\"");
      expect(html).toContain("data-testid=\"fixture-tab-completed\"");
      expect(html).toContain("data-testid=\"fixture-tab-failed\"");
    });

    it("omits fixture state selector when showFixtureToolbar is false", () => {
      const html = renderToStaticMarkup(
        <SketchViewer showFixtureToolbar={false} />
      );

      expect(html).not.toContain("data-testid=\"sketch-fixture-toolbar\"");
    });
  });
});
