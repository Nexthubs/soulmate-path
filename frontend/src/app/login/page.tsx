"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

function LoginContent() {
  return (
    <main className="min-h-screen max-w-[390px] mx-auto flex flex-col items-center justify-between p-6 bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de] text-neutral-900">
      <header className="w-full flex justify-between items-center py-4">
        <h1 className="font-serif text-[24px] text-neutral-900">Hint Soulmate</h1>
      </header>

      <div className="w-full bg-white/80 backdrop-blur-sm rounded-3xl p-6 shadow-sm border border-neutral-200/60 text-center space-y-4 my-auto">
        <div className="w-12 h-12 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center mx-auto text-xl">
          👤
        </div>
        <h2 className="text-xl font-bold text-neutral-900">Account Login</h2>
        <p className="text-sm text-neutral-600 leading-relaxed">
          Existing account authentication and session recovery will be enabled in Wave 2 (SP-201).
        </p>
        <Link
          href={SOULMATE_ROUTES.LANDING}
          className="inline-block w-full py-3 px-4 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold text-sm transition-colors"
        >
          Back to Home
        </Link>
      </div>

      <footer className="py-4 text-xs text-neutral-400">
        Hint Soulmate &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">Loading...</div>}>
      <LoginContent />
    </Suspense>
  );
}
