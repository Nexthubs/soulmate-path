"use client";

/**
 * DrawerMenuButton — shared trigger for the global AccountDrawer (SP-801).
 *
 * Inside the soulmate layout it opens the provider-mounted global drawer.
 * When rendered without a provider (standalone usage), it falls back to a
 * local instance of the SAME AccountDrawer component so the navigation
 * infrastructure is still never duplicated per page.
 */
import React, { useState } from "react";
import { useSoulmateDrawer } from "./DrawerProvider";
import { AccountDrawer } from "./AccountDrawer";
import { DEFAULT_SKETCH_DESTINATION } from "./nav";

export interface DrawerMenuButtonProps {
  className?: string;
}

export function DrawerMenuButton({ className }: DrawerMenuButtonProps) {
  const drawer = useSoulmateDrawer();
  const [fallbackOpen, setFallbackOpen] = useState(false);

  const handleOpen = () => {
    if (drawer) {
      drawer.openDrawer();
    } else {
      setFallbackOpen(true);
    }
  };

  const handleClose = () => {
    if (drawer) {
      drawer.closeDrawer();
    } else {
      setFallbackOpen(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        aria-label="Open menu"
        aria-haspopup="dialog"
        data-testid="drawer-menu-btn"
        className={
          className ??
          "flex h-9 w-9 items-center justify-center text-[#1b1b1b] hover:text-black focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 rounded-md"
        }
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M3 5.5H17M3 10H17M3 14.5H17"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {!drawer && (
        <AccountDrawer
          open={fallbackOpen}
          onClose={handleClose}
          sketchDestination={DEFAULT_SKETCH_DESTINATION}
        />
      )}
    </>
  );
}
