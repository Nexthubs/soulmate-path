import type { Metadata } from "next";
import { assertClientConfig } from "@/soulmate/config";
import { ConfigValidator } from "@/soulmate/components/ConfigValidator";
import { SoulmateDrawerProvider } from "@/soulmate/components/drawer";
import { SharedFlowProvider } from "@/soulmate/components/flow/SharedFlowContext";

export const metadata: Metadata = {
  title: "Soulmate Path - See the Face of Your Soulmate",
  description: "Astrology & psychic guided soulmate sketch and compatibility insights.",
};

export default function SoulmateLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Server-side runtime gate: validate production configuration on live server requests
  // Skipped during static build prerendering (NEXT_PHASE === "phase-production-build")
  if (
    typeof window === "undefined" &&
    process.env.NODE_ENV === "production" &&
    process.env.NEXT_PHASE !== "phase-production-build"
  ) {
    assertClientConfig();
  }

  return (
    // Full-width host (batch 1): no 390px card, no forced background here —
    // each page/shell owns its background and centers its own content slot.
    <main className="w-full flex flex-col relative sp-fill-vh">
      <ConfigValidator />
      <SharedFlowProvider>
        <SoulmateDrawerProvider>{children}</SoulmateDrawerProvider>
      </SharedFlowProvider>
    </main>
  );
}



