import { CANONICAL_QUIZ_VERSION } from "@/soulmate/domain";

export default function SoulmateRootPage() {
  return (
    <div className="flex flex-col min-h-screen px-6 py-8 bg-gradient-to-b from-[#fff5f5] via-[#fffbf2] to-white">
      {/* Top Bar */}
      <header className="flex items-center justify-between py-2">
        <h1 className="font-serif text-3xl tracking-tight text-neutral-900">
          Soulmate Path
        </h1>
        <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 font-medium border border-emerald-200">
          Module Active
        </span>
      </header>

      {/* Main Hero Smoke Content */}
      <div className="flex-1 flex flex-col justify-center items-center text-center my-auto space-y-6">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 text-amber-800 text-xs font-medium border border-amber-200/60">
          <span>✨</span>
          <span>Version: {CANONICAL_QUIZ_VERSION}</span>
        </div>

        <h2 className="text-2xl font-semibold tracking-tight text-neutral-900 max-w-xs leading-snug">
          See the Face of Your Soulmate
        </h2>

        <p className="text-sm text-neutral-600 max-w-xs leading-relaxed">
          The Soulmate Path feature route namespace is initialized and verified.
        </p>

        {/* CTA placeholder for SP-101 / SP-102 to avoid 404 dead link */}
        <div className="w-full pt-4 space-y-2">
          <button
            type="button"
            disabled
            className="w-full inline-flex justify-center items-center px-6 py-3.5 text-base font-medium text-white bg-neutral-900/80 cursor-not-allowed rounded-2xl shadow-sm"
          >
            Let&apos;s begin (Quiz wiring in SP-102)
          </button>
          <p className="text-[11px] text-neutral-400">
            Landing page implementation will land in SP-101
          </p>
        </div>
      </div>

      {/* Footer Info */}
      <footer className="text-center pt-6 pb-2 text-[11px] text-neutral-400">
        Soulmate Path V1 • Route Namespace &amp; Smoke Verified
      </footer>
    </div>
  );
}
