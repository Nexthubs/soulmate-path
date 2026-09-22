import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Soulmate Path - See the Face of Your Soulmate",
  description: "Astrology & psychic guided soulmate sketch and compatibility insights.",
};

export default function SoulmateLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <main className="w-full max-w-[390px] min-h-screen mx-auto flex flex-col relative shadow-sm bg-white">
      {children}
    </main>
  );
}
