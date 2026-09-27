/**
 * Drawer navigation model (DEV-SPEC §2; SP-801).
 *
 * The Soulmate Sketch entry is the primary product entry added by SP-801.
 * Its destination is injected by the caller: SP-802 replaces the default with
 * a server-authoritative, payment-status-aware resolution (PAY-AUTH-01, TIME-01).
 */
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";

export interface DrawerNavLink {
  label: string;
  href: string;
  testId: string;
}

/** Default destination for the Soulmate Sketch entry (SP-802 routing row 1: no successful first payment -> /soulmate). */
export const DEFAULT_SKETCH_DESTINATION = SOULMATE_ROUTES.LANDING;

/**
 * Ordered drawer navigation links.
 * Figma 102:14 defines the utility links (Privacy Policy / Terms of use /
 * Subscribe policy / Setting); SP-801 prepends the Soulmate Sketch entry.
 * Policy anchors are placeholders consistent with the landing footer until
 * dedicated legal pages exist.
 */
export function buildDrawerNavLinks(
  sketchDestination: string = DEFAULT_SKETCH_DESTINATION
): DrawerNavLink[] {
  return [
    {
      label: "Soulmate Sketch",
      // Reuse the repo-standard open-redirect guard (M-2) for injected destinations.
      href: sanitizeInternalRoute(sketchDestination, DEFAULT_SKETCH_DESTINATION),
      testId: "drawer-link-sketch",
    },
    { label: "Privacy Policy", href: "#privacy", testId: "drawer-link-privacy" },
    { label: "Terms of use", href: "#terms", testId: "drawer-link-terms" },
    {
      label: "Subscribe policy",
      href: "#subscribe-policy",
      testId: "drawer-link-subscribe-policy",
    },
    { label: "Setting", href: SOULMATE_ROUTES.SETTINGS, testId: "drawer-link-setting" },
  ];
}
