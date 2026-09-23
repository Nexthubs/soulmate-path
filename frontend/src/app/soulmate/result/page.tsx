"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SoulmateResultView } from "@/soulmate/components/result";

function ResultContent() {
  const searchParams = useSearchParams();
  const [email, setEmail] = React.useState<string>(
    searchParams.get("email") || ""
  );

  React.useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = sessionStorage.getItem("soulmate_user_email");
      if (stored) {
        setEmail(stored);
      }
    }
  }, []);

  const isProduction = process.env.NODE_ENV === "production";
  const showToolbar = !isProduction && (searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production");

  return (
    <>
      {!isProduction && (
        <div
          data-testid="result-fixture-banner"
          className="w-full max-w-[390px] mx-auto py-1 px-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-800 text-center text-xs font-semibold"
        >
          [Demo Preview (Fixture Data)]
        </div>
      )}
      <SoulmateResultView
        userEmail={email || "user@example.com"}
        showFixtureToolbar={showToolbar}
      />
    </>
  );
}

export default function SoulmateResultPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen text-neutral-400">
          Loading results...
        </div>
      }
    >
      <ResultContent />
    </Suspense>
  );
}
