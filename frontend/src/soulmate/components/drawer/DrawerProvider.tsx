"use client";

/**
 * DrawerProvider — mounts the single global AccountDrawer instance for all
 * /soulmate routes (DEV-SPEC §2 "Global"; SP-801 acceptance: no duplicated
 * global navigation infrastructure). Pages open it via useSoulmateDrawer()
 * or the shared DrawerMenuButton instead of rendering their own drawer.
 *
 * SP-802: unless an explicit `sketchDestination` override is provided, the
 * Soulmate Sketch destination is resolved from the server-authoritative
 * result aggregate (SP-503) each time the drawer opens — never from a local
 * membership flag (PAY-AUTH-01, TIME-01).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { AccountDrawer } from "./AccountDrawer";
import {
  DEFAULT_SKETCH_DESTINATION,
  resolveDrawerSketchDestination,
} from "./nav";
import { getResultAggregate } from "@/soulmate/api/result";

export interface SoulmateDrawerContextValue {
  isOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

const DrawerContext = createContext<SoulmateDrawerContextValue | null>(null);

export interface SoulmateDrawerProviderProps {
  children: React.ReactNode;
  /**
   * Explicit destination override. When omitted (production default), the
   * destination is resolved from the server result aggregate on every open:
   * 403/no-payment or fetch failure -> /soulmate; LOCKED -> /soulmate/result;
   * any unlocked state -> /soulmate/sketch.
   */
  sketchDestination?: string;
  /** Optional logout handler forwarded to the drawer (auth pending in V1). */
  onLogout?: () => void;
}

function errorStatusOf(err: unknown): number | null {
  if (typeof err === "object" && err !== null && "status" in err) {
    const status = Number((err as { status: unknown }).status);
    return Number.isFinite(status) ? status : null;
  }
  return null;
}

export function SoulmateDrawerProvider({
  children,
  sketchDestination,
  onLogout,
}: SoulmateDrawerProviderProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [resolvedDestination, setResolvedDestination] = useState<string | null>(null);

  const openDrawer = useCallback(() => setIsOpen(true), []);
  const closeDrawer = useCallback(() => setIsOpen(false), []);
  const value = useMemo(
    () => ({ isOpen, openDrawer, closeDrawer }),
    [isOpen, openDrawer, closeDrawer]
  );

  // Server-authoritative destination resolution (SP-802): one aggregate fetch
  // per open. No session_id argument — the HttpOnly session cookie is the
  // identity, so no local session flag can influence the outcome.
  useEffect(() => {
    if (sketchDestination || !isOpen) return;

    let cancelled = false;
    getResultAggregate()
      .then((aggregate) => {
        if (!cancelled) {
          setResolvedDestination(resolveDrawerSketchDestination(aggregate, null));
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setResolvedDestination(resolveDrawerSketchDestination(null, errorStatusOf(err)));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, sketchDestination]);

  const effectiveDestination = sketchDestination ?? resolvedDestination ?? DEFAULT_SKETCH_DESTINATION;

  return (
    <DrawerContext.Provider value={value}>
      {children}
      <AccountDrawer
        open={isOpen}
        onClose={closeDrawer}
        sketchDestination={effectiveDestination}
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
