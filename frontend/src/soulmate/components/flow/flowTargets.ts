import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

/**
 * Single source for step-code -> funnel-route derivation and prefetching
 * (batch 3 §6.5). Both the quiz and the loading page resolve navigation and
 * prefetch targets through this helper so no page keeps a second private
 * step mapping.
 */
export function flowRouteForStep(step: string): string | null {
  if (step.startsWith("transition_")) {
    return `/soulmate/loading?step=${step.replace("transition_", "")}`;
  }
  if (step.startsWith("q")) {
    return `/soulmate/quiz?code=${step}`;
  }
  if (step === "email") {
    return "/soulmate/email";
  }
  return null;
}

/**
 * Best-effort prefetch of the confirmed target route. Never throws; prefetch
 * failures are non-fatal because the actual navigation still resolves the
 * route (and the server still authorizes the step).
 */
export function prefetchFlowRoute(router: AppRouterInstance, nextStep: string): void {
  const route = flowRouteForStep(nextStep);
  if (!route) return;
  try {
    router.prefetch(route);
  } catch {
    // Prefetch is an optimization only.
  }
}
