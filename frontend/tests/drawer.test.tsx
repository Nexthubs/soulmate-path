/**
 * SP-801 + SP-802: Drawer Soulmate entry and status-aware destination
 * (DEV-SPEC §2–3, §10; Figma 102:14; Decisions: DOMAIN-01, PAY-AUTH-01, TIME-01).
 *
 * Acceptance criteria under test:
 * - a global AccountDrawer exists as the single navigation infrastructure
 *   (provider-mounted; pages never re-implement it);
 * - the drawer adds the `Soulmate Sketch` entry (first position);
 * - SP-802: the entry destination derives from server-authoritative status —
 *   no confirmed first payment (403) -> /soulmate; sketch LOCKED -> /result;
 *   any unlocked combined state -> /sketch — never a local membership flag;
 * - Figma 102:14 utility links are preserved with canonical route targets;
 * - the shared trigger is wired into the landing header.
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  AccountDrawer,
  SoulmateDrawerProvider,
  DrawerMenuButton,
  buildDrawerNavLinks,
  DEFAULT_SKETCH_DESTINATION,
  resolveSketchDestinationFromStatus,
  resolveDrawerSketchDestination,
} from "../src/soulmate/components/drawer";
import { SOULMATE_ROUTES } from "../src/soulmate/domain";
import { ResultAggregateResponse } from "../src/soulmate/api/result";
import { SoulmateLandingPage } from "../src/soulmate/components/landing/SoulmateLandingPage";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
    replace: vi.fn(),
  }),
}));

describe("SP-801: buildDrawerNavLinks (nav model)", () => {
  it("places the Soulmate Sketch entry first with the default non-status destination", () => {
    const links = buildDrawerNavLinks();

    expect(links[0].label).toBe("Soulmate Sketch");
    expect(links[0].href).toBe(SOULMATE_ROUTES.LANDING);
    expect(DEFAULT_SKETCH_DESTINATION).toBe(SOULMATE_ROUTES.LANDING);
  });

  it("preserves the Figma 102:14 utility links with canonical targets", () => {
    const links = buildDrawerNavLinks();
    const labels = links.map((link) => link.label);

    expect(labels).toEqual([
      "Soulmate Sketch",
      "Privacy Policy",
      "Terms of use",
      "Subscribe policy",
      "Setting",
    ]);
    expect(links.find((l) => l.label === "Setting")?.href).toBe(SOULMATE_ROUTES.SETTINGS);
  });

  it("accepts an injectable destination for SP-802 status-aware routing", () => {
    const links = buildDrawerNavLinks(SOULMATE_ROUTES.RESULT);
    expect(links[0].href).toBe(SOULMATE_ROUTES.RESULT);

    const sketchLinks = buildDrawerNavLinks(SOULMATE_ROUTES.SKETCH);
    expect(sketchLinks[0].href).toBe(SOULMATE_ROUTES.SKETCH);
  });

  it("sanitizes unsafe injected destinations via the repo open-redirect guard (M-2)", () => {
    expect(buildDrawerNavLinks("https://evil.example")[0].href).toBe(SOULMATE_ROUTES.LANDING);
    expect(buildDrawerNavLinks("//evil.example/path")[0].href).toBe(SOULMATE_ROUTES.LANDING);
    expect(buildDrawerNavLinks("/not-an-allowed-route")[0].href).toBe(SOULMATE_ROUTES.LANDING);
  });
});

describe("SP-801: AccountDrawer (Figma 102:14 parity)", () => {
  it("renders nothing when closed", () => {
    const html = renderToStaticMarkup(<AccountDrawer open={false} onClose={() => {}} />);
    expect(html).toBe("");
  });

  it("renders the 312px sidebar dialog with backdrop and close affordance when open", () => {
    const html = renderToStaticMarkup(<AccountDrawer open onClose={() => {}} />);

    expect(html).toContain('data-testid="account-drawer"');
    expect(html).toContain('data-testid="drawer-backdrop"');
    expect(html).toContain('data-testid="drawer-close-btn"');
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-label="Account menu"');
    expect(html).toContain('aria-label="Close menu"');
    // Figma 102:26 — 312px white panel anchored to the 390px shell
    expect(html).toContain("w-[312px]");
    expect(html).toContain("bg-white");
    // Figma 102:15 — 50% black scrim
    expect(html).toContain("bg-black/50");
  });

  it("includes the Soulmate Sketch entry and all utility links plus Log out", () => {
    const html = renderToStaticMarkup(<AccountDrawer open onClose={() => {}} />);

    expect(html).toContain('data-testid="drawer-link-sketch"');
    expect(html).toContain("Soulmate Sketch");
    expect(html).toContain("Privacy Policy");
    expect(html).toContain("Terms of use");
    expect(html).toContain("Subscribe policy");
    expect(html).toContain("Setting");
    expect(html).toContain('data-testid="drawer-logout-btn"');
    expect(html).toContain("Log out");

    // Soulmate Sketch is the first navigation entry
    const sketchPos = html.indexOf('data-testid="drawer-link-sketch"');
    const privacyPos = html.indexOf('data-testid="drawer-link-privacy"');
    expect(sketchPos).toBeGreaterThan(-1);
    expect(privacyPos).toBeGreaterThan(sketchPos);
  });

  it("respects an injected sketch destination (SP-802 extension point)", () => {
    const html = renderToStaticMarkup(
      <AccountDrawer open onClose={() => {}} sketchDestination={SOULMATE_ROUTES.RESULT} />
    );
    expect(html).toContain(`href="${SOULMATE_ROUTES.RESULT}"`);
  });

  it("does not invent a balance card (Figma 102:43 is empty in the design source)", () => {
    const html = renderToStaticMarkup(<AccountDrawer open onClose={() => {}} />);
    expect(html.toLowerCase()).not.toContain("balance");
  });
});

describe("SP-802: status-aware drawer destination (server-authoritative)", () => {
  const aggregateWith = (
    sketchStatus: ResultAggregateResponse["sketch"]["status"]
  ): ResultAggregateResponse => ({
    session_id: "session-test",
    server_time: "2026-09-27T12:00:00Z",
    subscription: {
      provider: "paypal",
      provider_status: "ACTIVE",
      first_payment_at: "2026-09-26T12:00:00Z",
      next_billing_at: "2026-10-26T12:00:00Z",
    },
    sketch: {
      unlock_at: "2026-09-27T00:00:00Z",
      availability: sketchStatus === "LOCKED" ? "LOCKED" : "UNLOCKED",
      generation: "NOT_STARTED",
      status: sketchStatus,
    },
    report: {
      unlock_at: "2026-09-27T12:00:00Z",
      availability: "LOCKED",
      generation: "NOT_STARTED",
      status: "LOCKED",
    },
  });

  it("maps the §10.3 combined sketch status per the SP-802 routing table", () => {
    // paid, sketch locked -> /soulmate/result
    expect(resolveSketchDestinationFromStatus("LOCKED")).toBe(SOULMATE_ROUTES.RESULT);
    // unlocked/generating (READY, GENERATING, FAILED) and completed -> /soulmate/sketch
    expect(resolveSketchDestinationFromStatus("READY")).toBe(SOULMATE_ROUTES.SKETCH);
    expect(resolveSketchDestinationFromStatus("GENERATING")).toBe(SOULMATE_ROUTES.SKETCH);
    expect(resolveSketchDestinationFromStatus("COMPLETED")).toBe(SOULMATE_ROUTES.SKETCH);
    expect(resolveSketchDestinationFromStatus("FAILED")).toBe(SOULMATE_ROUTES.SKETCH);
    // unknown / not yet loaded stays conservative on the paying user's home base
    expect(resolveSketchDestinationFromStatus(null)).toBe(SOULMATE_ROUTES.RESULT);
    expect(resolveSketchDestinationFromStatus(undefined)).toBe(SOULMATE_ROUTES.RESULT);
    // Wave 8 audit M-1: unrecognized status values are NOT mapped to Sketch
    expect(resolveSketchDestinationFromStatus("SOMETHING_ELSE")).toBe(SOULMATE_ROUTES.RESULT);
    expect(resolveSketchDestinationFromStatus("")).toBe(SOULMATE_ROUTES.RESULT);
  });

  it("resolves from the SP-503 aggregate payload when authorized (200)", () => {
    expect(resolveDrawerSketchDestination(aggregateWith("LOCKED"), null)).toBe(
      SOULMATE_ROUTES.RESULT
    );
    expect(resolveDrawerSketchDestination(aggregateWith("COMPLETED"), null)).toBe(
      SOULMATE_ROUTES.SKETCH
    );
    expect(resolveDrawerSketchDestination(aggregateWith("GENERATING"), null)).toBe(
      SOULMATE_ROUTES.SKETCH
    );
  });

  it("falls back to /soulmate on 403 (no confirmed first payment, PAY-AUTH-01)", () => {
    expect(resolveDrawerSketchDestination(null, 403)).toBe(SOULMATE_ROUTES.LANDING);
    expect(resolveDrawerSketchDestination(null, 500)).toBe(SOULMATE_ROUTES.LANDING);
    expect(resolveDrawerSketchDestination(null, null)).toBe(SOULMATE_ROUTES.LANDING);
    expect(DEFAULT_SKETCH_DESTINATION).toBe(SOULMATE_ROUTES.LANDING);
  });

  it("keeps the entry inside the sanitized internal route space for every outcome", () => {
    const outcomes = [
      resolveDrawerSketchDestination(aggregateWith("LOCKED"), null),
      resolveDrawerSketchDestination(aggregateWith("COMPLETED"), null),
      resolveDrawerSketchDestination(null, 403),
    ];
    for (const destination of outcomes) {
      expect(
        buildDrawerNavLinks(destination).find((l) => l.testId === "drawer-link-sketch")?.href
      ).toBe(destination);
    }
  });
});

describe("SP-801: global mounting without duplicated infrastructure", () => {
  it("provider renders children and keeps the drawer closed by default", () => {
    const html = renderToStaticMarkup(
      <SoulmateDrawerProvider>
        <div>page-content</div>
      </SoulmateDrawerProvider>
    );

    expect(html).toContain("page-content");
    expect(html).not.toContain('data-testid="account-drawer"');
  });

  it("DrawerMenuButton renders the shared trigger (works standalone and under provider)", () => {
    const standalone = renderToStaticMarkup(<DrawerMenuButton />);
    expect(standalone).toContain('data-testid="drawer-menu-btn"');
    expect(standalone).toContain('aria-label="Open menu"');
    expect(standalone).toContain('aria-haspopup="dialog"');

    const underProvider = renderToStaticMarkup(
      <SoulmateDrawerProvider>
        <DrawerMenuButton />
      </SoulmateDrawerProvider>
    );
    expect(underProvider).toContain('data-testid="drawer-menu-btn"');
    expect(underProvider).not.toContain('data-testid="account-drawer"');
  });

  it("wires the shared trigger into the landing header (Figma drawer context is the landing page)", () => {
    const html = renderToStaticMarkup(<SoulmateLandingPage />);
    expect(html).toContain('data-testid="drawer-menu-btn"');
    expect(html).toContain("Login");
    expect(html).toContain('href="/login"');
  });
});
