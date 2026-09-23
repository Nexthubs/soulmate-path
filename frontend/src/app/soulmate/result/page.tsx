"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SoulmateResultView } from "@/soulmate/components/result";

function ResultContent() {
  const searchParams = useSearchParams();
  const [email, setEmail] = React.useState<string>(
    searchParams.get("email") || "weijialin0827@gmail.com"
  );

  React.useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = sessionStorage.getItem("soulmate_user_email");
      if (stored) {
        setEmail(stored);
      }
    }
  }, []);

  const showToolbar = searchParams.get("fixture") === "true" || process.env.NODE_ENV !== "production";

  return (
    <SoulmateResultView
      userEmail={email}
      showFixtureToolbar={showToolbar}
    />
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
