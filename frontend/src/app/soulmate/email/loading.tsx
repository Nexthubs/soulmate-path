/**
 * Route-level instant loading boundary for /soulmate/email (Next.js App Router).
 *
 * Arriving from the Transition-5 interstitials is a real navigation whose RSC
 * payload takes one round trip; this skeleton renders the moment the
 * navigation starts and is statically prerendered/prefetchable. Visuals mirror
 * the funnel's warm gradient so the swap reads as continuous instead of a
 * white flash from the page's inline text fallback.
 */
export default function SoulmateEmailRouteSkeleton() {
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
