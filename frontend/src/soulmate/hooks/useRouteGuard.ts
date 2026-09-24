"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { checkRouteGuard, RouteGuardResponse } from "../api/guard";

export const HIGH_VALUE_ROUTES = [
  "/soulmate/result",
  "/soulmate/sketch",
  "/soulmate/report",
] as const;

export interface UseRouteGuardOptions {
  targetRoute: string;
  sessionId?: string;
  enabled?: boolean;
  /**
   * If true (default), network errors or API failures block access (fail-closed).
   * HIGH-RISK INVARIANT (PAY-AUTH-01 / DEV-SPEC §3):
   * High-value routes (/result, /sketch, /report) ALWAYS fail-closed unconditionally.
   */
  failClosed?: boolean;
}

export interface UseRouteGuardResult {
  allowed: boolean | null;
  loading: boolean;
  verdict: RouteGuardResponse | null;
  error: string | null;
  retry: () => void;
}

/**
 * Determines whether a route check failure must fail closed (block access) or fail open.
 * High-value paid routes (/result, /sketch, /report) MUST strictly fail-closed (PAY-AUTH-01).
 */
export function resolveGuardFailurePolicy(
  targetRoute: string,
  options?: { failClosed?: boolean }
): { allowed: boolean; shouldBlock: boolean } {
  const isHighValue = HIGH_VALUE_ROUTES.some((route) => targetRoute.startsWith(route));
  const enforceFailClosed = isHighValue || (options?.failClosed ?? true);

  return {
    allowed: !enforceFailClosed,
    shouldBlock: enforceFailClosed,
  };
}

/**
 * Client-side route guard hook enforcing server-authoritative verdicts (DEV-SPEC §3, PAY-AUTH-01).
 * If server evaluates allowed=false, automatically redirects to server-specified redirect_to.
 * Under API/network failure, enforces fail-closed policy (C-1 remediation).
 */
export function useRouteGuard({
  targetRoute,
  sessionId,
  enabled = true,
  failClosed = true,
}: UseRouteGuardOptions): UseRouteGuardResult {
  let router: ReturnType<typeof useRouter> | null = null;
  try {
    router = useRouter();
  } catch {
    router = null;
  }

  const [loading, setLoading] = useState(enabled);
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [verdict, setVerdict] = useState<RouteGuardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  const retry = useCallback(() => {
    setRetryCount((prev) => prev + 1);
  }, []);

  const failurePolicy = resolveGuardFailurePolicy(targetRoute, { failClosed });

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      setAllowed(true);
      return;
    }

    let isMounted = true;

    async function evaluate() {
      try {
        setLoading(true);
        const res = await checkRouteGuard(targetRoute, sessionId);
        if (isMounted) {
          setVerdict(res);
          setAllowed(res.allowed);
          setError(null);

          if (!res.allowed && res.redirect_to && router) {
            router.replace(res.redirect_to);
          }
        }
      } catch (err: unknown) {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : "Route guard check failed";
          setError(msg);
          // High-risk invariant (DEV-SPEC §3, PAY-AUTH-01): Fail-closed on error
          setAllowed(failurePolicy.allowed);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    evaluate();

    return () => {
      isMounted = false;
    };
  }, [targetRoute, sessionId, enabled, router, failurePolicy.allowed, retryCount]);

  return { allowed, loading, verdict, error, retry };
}
