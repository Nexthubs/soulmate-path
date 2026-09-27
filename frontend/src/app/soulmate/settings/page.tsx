"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getSubscriptionStatus, SubscriptionStatusResponse } from "@/soulmate/api/subscription";
import { getSketchStatus } from "@/soulmate/api/sketch";
import { getReportStatus } from "@/soulmate/api/report";
import { SavedArtifactLinks, SubscriptionSettingsAction } from "@/soulmate/components/settings";
import { DrawerMenuButton } from "@/soulmate/components/drawer";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function SettingsContent() {
  const searchParams = useSearchParams();
  const sessionIdParam = searchParams.get("session_id") || undefined;
  const [subData, setSubData] = useState<SubscriptionStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [savedArtifacts, setSavedArtifacts] = useState({ sketch: false, report: false });

  useEffect(() => {
    let isMounted = true;

    async function loadStatus() {
      try {
        setLoading(true);
        setError(null);
        const data = await getSubscriptionStatus(sessionIdParam, true);
        if (isMounted) {
          setSubData(data);
        }
      } catch (err: unknown) {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : "Failed to load subscription settings.";
          setError(msg);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    loadStatus();

    return () => {
      isMounted = false;
    };
  }, [sessionIdParam]);

  useEffect(() => {
    let isMounted = true;
    // Fetch independently of subscription-status reconciliation: a PayPal
    // outage must not hide already-owned, completed content. These reads are
    // session-authenticated; after expiry only completed artifacts are served.
    Promise.all([
      getSketchStatus(sessionIdParam).then((value) => value.sketch.status === "COMPLETED" && Boolean(value.image_url)).catch(() => false),
      getReportStatus(sessionIdParam).then((value) => value.report.status === "COMPLETED" && Boolean(value.content)).catch(() => false),
    ]).then(([sketch, report]) => {
      if (isMounted) setSavedArtifacts({ sketch, report });
    });
    return () => {
      isMounted = false;
    };
  }, [sessionIdParam]);

  return (
    <main
      data-testid="soulmate-settings-page"
      className="min-h-screen max-w-[420px] mx-auto flex flex-col justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900"
    >
      <header className="w-full flex items-center justify-between py-4 border-b border-rose-100/60 mb-6">
        <Link
          href={SOULMATE_ROUTES.RESULT}
          data-testid="settings-back-btn"
          className="text-xs font-semibold text-neutral-600 hover:text-neutral-900 flex items-center gap-1 transition-colors"
        >
          <span>&larr;</span> Back to Result
        </Link>
        <div className="flex items-center gap-2">
          <span className="font-serif italic font-bold text-[22px] tracking-tight text-[#2c1e4a]">
            Hint
          </span>
          {/* Shared trigger for the global AccountDrawer (SP-801/803; Figma 102:1423 places the trigger here) */}
          <DrawerMenuButton />
        </div>
      </header>

      <div className="flex-1 w-full space-y-6">
        <div className="space-y-1">
          <h1 className="font-sans font-extrabold text-[22px] tracking-tight text-neutral-900">
            Subscription &amp; Membership
          </h1>
          <p className="text-xs text-neutral-500">
            Manage your recurring membership and cancellation options anytime.
          </p>
        </div>

        {loading ? (
          <div
            data-testid="settings-loading"
            className="flex flex-col items-center justify-center p-12 space-y-3 bg-white/70 rounded-2xl border border-rose-100"
          >
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600" />
            <p className="text-xs text-neutral-500">Loading your membership details...</p>
          </div>
        ) : error ? (
          <div
            data-testid="settings-error"
            className="p-6 bg-white/80 rounded-2xl border border-rose-200 text-center space-y-3"
          >
            <p className="text-sm text-rose-700 font-medium">{error}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 text-xs font-semibold rounded-xl bg-purple-600 text-white hover:bg-purple-700 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : !subData || subData.status === "NONE" ? (
          <div
            data-testid="settings-no-subscription"
            className="p-6 bg-white/80 rounded-2xl border border-rose-100 text-center space-y-4"
          >
            <p className="text-sm text-neutral-600">No active subscription found for this session.</p>
            <Link
              href={SOULMATE_ROUTES.SUBSCRIBE}
              className="inline-block px-5 py-2.5 rounded-xl bg-purple-600 text-white text-xs font-bold hover:bg-purple-700 transition-colors"
            >
              View Membership Offers
            </Link>
          </div>
        ) : (
          <SubscriptionSettingsAction
            status={subData.status}
            isPaid={subData.is_paid}
            subscriptionId={subData.subscription_id}
            planId={subData.plan_id}
            currency={subData.currency}
            regularPrice={subData.regular_price}
            priceVerified={subData.price_verified}
            nextBillingAt={subData.next_billing_at}
            paidThroughAt={subData.paid_through_at}
            cancelledAt={subData.cancelled_at}
            sessionId={sessionIdParam}
          />
        )}

        <div className="rounded-2xl bg-amber-500/10 border border-amber-500/20 p-4 text-xs text-amber-900 space-y-1">
          <p className="font-semibold">✦ Artifact Preservation Guarantee (DEV-SPEC §9.8, ASSET-01)</p>
          <p className="text-[11px] leading-relaxed text-amber-800">
            Even if you cancel your subscription, all your generated Soulmate Sketches and Personality Reports
            remain permanently saved and accessible in your account.
          </p>
          <SavedArtifactLinks sketch={savedArtifacts.sketch} report={savedArtifacts.report} />
        </div>
      </div>

      <footer className="w-full py-6 text-center text-xs text-neutral-400 mt-6 border-t border-rose-100/60">
        Hint Soulmate &copy; {new Date().getFullYear()} &bull; All Rights Reserved
      </footer>
    </main>
  );
}

export default function SoulmateSettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center p-6 bg-gradient-to-b from-[#fff0f3] to-[#fef3de]">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600" />
        </div>
      }
    >
      <SettingsContent />
    </Suspense>
  );
}
