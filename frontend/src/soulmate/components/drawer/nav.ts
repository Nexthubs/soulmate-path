/**
 * Drawer navigation model (DEV-SPEC §2, §10; SP-801, SP-802).
 *
 * The Soulmate Sketch entry's destination is resolved from server-authoritative
 * status (PAY-AUTH-01, TIME-01): never from a local membership flag alone.
 */
import { SOULMATE_ROUTES, sanitizeInternalRoute } from "@/soulmate/domain";
import type { ResultAggregateResponse } from "@/soulmate/api/result";

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

/**
 * SP-802 routing: map the server-derived §10.3 combined sketch status to the
 * Soulmate Sketch destination.
 *
 * Only the known §10.2/§10.3 combined states are interpreted:
 * - LOCKED (or unknown / not-yet-loaded / unrecognized values) ->
 *   /soulmate/result, the paying user's conservative home base;
 * - the unlocked states READY / GENERATING / COMPLETED / FAILED ->
 *   /soulmate/sketch, which natively renders the ready / loading / completed /
 *   failed states per §10.3 and SP-607 and satisfies the §3 guard in all of
 *   them (Wave 8 audit M-1: unknown statuses no longer map to Sketch).
 */
export function resolveSketchDestinationFromStatus(
  sketchStatus: string | null | undefined
): string {
  const KNOWN_UNLOCKED_STATUSES = new Set(["READY", "GENERATING", "COMPLETED", "FAILED"]);
  if (sketchStatus != null && KNOWN_UNLOCKED_STATUSES.has(sketchStatus)) {
    return SOULMATE_ROUTES.SKETCH;
  }
  return SOULMATE_ROUTES.RESULT;
}

/**
 * SP-802 acceptance: the destination comes from server-authoritative status,
 * not a local membership flag. `aggregate` is the SP-503 result payload;
 * `errorStatus` is the HTTP status of its failure.
 *
 * - 403 (anonymous / IDOR / no confirmed first payment per PAY-AUTH-01) and
 *   any other fetch failure -> routing row 1: /soulmate (safe default).
 * - 200 payload -> resolved from the combined sketch status above.
 */
export function resolveDrawerSketchDestination(
  aggregate: ResultAggregateResponse | null,
  errorStatus: number | null
): string {
  if (errorStatus !== null || aggregate === null) {
    return DEFAULT_SKETCH_DESTINATION;
  }
  return resolveSketchDestinationFromStatus(aggregate.sketch?.status);
}
