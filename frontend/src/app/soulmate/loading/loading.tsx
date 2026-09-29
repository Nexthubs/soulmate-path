/**
 * Route-level instant loading boundary for /soulmate/loading (Next.js App Router).
 *
 * Cross-route moves (quiz <-> transition screens) are real navigations whose
 * RSC payload takes one round trip; this skeleton renders the moment the
 * navigation starts and is statically prerendered/prefetchable. Visuals mirror
 * TransitionShell/QuizShell (same 390px warm gradient) so the swap reads as
 * continuous instead of a white flash from the pages' inline text fallbacks.
 */
export default function SoulmateLoadingRouteSkeleton() {
  return (
    <div className="flex flex-col min-h-screen items-center justify-center w-full max-w-[390px] mx-auto bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de]">
      <div
        className="h-8 w-8 animate-spin rounded-full border-[3px] border-purple-200 border-t-purple-600"
        role="status"
        aria-label="Loading"
      />
    </div>
  );
}
