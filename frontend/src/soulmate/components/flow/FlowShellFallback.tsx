/**
 * Unified funnel shell fallback for every Suspense boundary on the /soulmate
 * path (route-level and inline). Mirrors the full-width warm gradient of
 * QuizShell/TransitionShell (batch 1) so cold entries and client navigations
 * never flash a bare white screen between richly colored pages (UI continuity,
 * DEV-SPEC §2).
 */
export function FlowShellFallback() {
  return (
    <div className="flex flex-col sp-fill-vh items-center justify-center w-full bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de]">
      <div
        className="h-8 w-8 animate-spin rounded-full border-[3px] border-purple-200 border-t-purple-600"
        role="status"
        aria-label="Loading"
      />
    </div>
  );
}
