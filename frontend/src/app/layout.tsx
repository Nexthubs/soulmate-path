import type { Metadata, Viewport } from "next";
import { Poppins, Instrument_Serif } from "next/font/google";
import "./globals.css";

const poppins = Poppins({
  weight: ["300", "400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-poppins",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  weight: ["400"],
  subsets: ["latin"],
  variable: "--font-instrument-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Soulmate Path",
  description: "Astrology & psychic guided soulmate sketch and compatibility insights.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${poppins.variable} ${instrumentSerif.variable}`}>
      <body className="antialiased min-h-screen w-full bg-[#fdfaf7] text-neutral-800">
        {children}
      </body>
    </html>
  );
}
