"use client";

/**
 * AccountDrawer — global account/navigation drawer (DEV-SPEC §2, Figma node 102:14).
 *
 * Single shared instance of the global navigation infrastructure: pages trigger
 * it via SoulmateDrawerProvider / DrawerMenuButton and must never re-implement
 * the drawer themselves (SP-801 acceptance).
 *
 * Visual contract (Figma 102:14): white 312px left sidebar over a 50% black
 * backdrop, Poppins Medium 20px / 28px line-height / 1px letter-spacing links
 * in #1b1b1b, close button at 48/32/32 padding. The Soulmate Sketch entry is
 * prepended by SP-801; its destination defaults to /soulmate until SP-802
 * resolves it from server-authoritative status.
 */
import React, { useEffect, useRef } from "react";
import Link from "next/link";
import { buildDrawerNavLinks, DEFAULT_SKETCH_DESTINATION } from "./nav";

export interface AccountDrawerProps {
  /** Whether the drawer is currently open. */
  open: boolean;
  /** Called when the user dismisses the drawer (close button, backdrop, Escape). */
  onClose: () => void;
  /**
   * Destination of the Soulmate Sketch entry. Defaults to /soulmate.
   * SP-802 replaces this with a server-authoritative status-aware resolution.
   */
  sketchDestination?: string;
  /**
   * Logout handler. Authentication does not exist yet in V1 scope, so the
   * default is a no-op placeholder; wire the real action when auth lands.
   */
  onLogout?: () => void;
}

export function AccountDrawer({
  open,
  onClose,
  sketchDestination = DEFAULT_SKETCH_DESTINATION,
  onLogout,
}: AccountDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const previousActive = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousActive?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const links = buildDrawerNavLinks(sketchDestination);
  const linkClassName =
    "font-medium text-[20px] leading-[28px] tracking-[1px] text-[#1b1b1b] hover:text-black focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded-sm";

  return (
    <div data-testid="account-drawer-root">
      {/* Backdrop (Figma 102:15) — 50% black scrim over the page behind */}
      <div
        data-testid="drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/50"
      />

      {/* Sidebar Menu Overlay (Figma 102:26) — 312px white panel, aligned to the 390px shell */}
      <aside
        data-testid="account-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Account menu"
        className="fixed top-0 bottom-0 left-[max(0px,calc(50%_-_195px))] z-50 flex w-[312px] flex-col bg-white shadow-xl"
      >
        {/* Close Button (Figma 102:27): padding 48 / 32 / 32, 16px icon in #484550 */}
        <div className="px-8 pt-12 pb-8">
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            data-testid="drawer-close-btn"
            className="flex h-8 w-8 items-center justify-center text-[#484550] hover:text-black focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded-sm"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M2 2L14 14M14 2L2 14"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {/* Navigation Links (Figma 102:31): 32px side padding, 24px gaps, Log out +8px (102:40) */}
        <nav data-testid="drawer-nav" aria-label="Account menu navigation" className="flex flex-col gap-6 px-8 pt-4 pb-4">
          {links.map((link) => (
            <Link key={link.testId} href={link.href} data-testid={link.testId} className={linkClassName} onClick={onClose}>
              {link.label}
            </Link>
          ))}
          <button
            type="button"
            onClick={onLogout}
            data-testid="drawer-logout-btn"
            className={`mt-2 text-left ${linkClassName}`}
          >
            Log out
          </button>
        </nav>

        {/*
          Balance Card area (Figma 102:43) is intentionally not rendered:
          it is empty in the design source and its content belongs to a
          future task — do not invent placeholder balance UI.
        */}
      </aside>
    </div>
  );
}
