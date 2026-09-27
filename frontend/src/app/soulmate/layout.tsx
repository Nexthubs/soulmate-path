import type { Metadata } from "next";
import { assertClientConfig } from "@/soulmate/config";
import { ConfigValidator } from "@/soulmate/components/ConfigValidator";
import { SoulmateDrawerProvider } from "@/soulmate/components/drawer";

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
    <main className="w-full max-w-[390px] min-h-screen mx-auto flex flex-col relative shadow-sm bg-white">
      <ConfigValidator />
      <SoulmateDrawerProvider>{children}</SoulmateDrawerProvider>
    </main>
  );
}



