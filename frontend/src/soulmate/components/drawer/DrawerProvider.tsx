"use client";

/**
 * DrawerProvider — mounts the single global AccountDrawer instance for all
 * /soulmate routes (DEV-SPEC §2 "Global"; SP-801 acceptance: no duplicated
 * global navigation infrastructure). Pages open it via useSoulmateDrawer()
 * or the shared DrawerMenuButton instead of rendering their own drawer.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { AccountDrawer } from "./AccountDrawer";
import { DEFAULT_SKETCH_DESTINATION } from "./nav";

export interface SoulmateDrawerContextValue {
  isOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

const DrawerContext = createContext<SoulmateDrawerContextValue | null>(null);

export interface SoulmateDrawerProviderProps {
  children: React.ReactNode;
  /**
   * Destination for the Soulmate Sketch entry. Defaults to /soulmate.
   * SP-802 will drive this from server-authoritative payment/unlock status.
   */
  sketchDestination?: string;
  /** Optional logout handler forwarded to the drawer (auth pending in V1). */
  onLogout?: () => void;
}

export function SoulmateDrawerProvider({
  children,
  sketchDestination = DEFAULT_SKETCH_DESTINATION,
  onLogout,
}: SoulmateDrawerProviderProps) {
  const [isOpen, setIsOpen] = useState(false);
  const openDrawer = useCallback(() => setIsOpen(true), []);
  const closeDrawer = useCallback(() => setIsOpen(false), []);
  const value = useMemo(
    () => ({ isOpen, openDrawer, closeDrawer }),
    [isOpen, openDrawer, closeDrawer]
  );

  return (
    <DrawerContext.Provider value={value}>
      {children}
      <AccountDrawer
        open={isOpen}
        onClose={closeDrawer}
        sketchDestination={sketchDestination}
        onLogout={onLogout}
      />
    </DrawerContext.Provider>
  );
}

/**
 * Returns the global drawer controls, or null when no provider is mounted
 * (e.g. standalone component rendering). Production /soulmate pages always
 * run inside SoulmateDrawerProvider via the soulmate layout.
 */
export function useSoulmateDrawer(): SoulmateDrawerContextValue | null {
  return useContext(DrawerContext);
}
