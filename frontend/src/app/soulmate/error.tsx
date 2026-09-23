"use client";

export interface SoulmateErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * Route-level Error Boundary for /soulmate (SP-004).
 * Catches client rendering and configuration exceptions, presenting a graceful user-facing state.
 */
export default function SoulmateError({ error, reset }: SoulmateErrorProps) {
  if (typeof window !== "undefined") {
    console.error("[Soulmate Error Boundary]", error);
  }

  const isConfigError = error?.message?.includes("Production client configuration validation failed");

  return (
    <div
      data-testid="soulmate-error-boundary"
      className="w-full max-w-[390px] min-h-screen mx-auto flex flex-col items-center justify-center p-6 text-center bg-white shadow-sm"
    >
      <div className="w-16 h-16 mb-4 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-2xl font-bold">
        !
      </div>
      <h2 className="text-xl font-semibold text-gray-900 mb-2" data-testid="error-title">
        {isConfigError ? "Service Temporarily Unavailable" : "Something Went Wrong"}
      </h2>
      <p className="text-sm text-gray-600 mb-6 max-w-xs leading-relaxed" data-testid="error-description">
        {process.env.NODE_ENV === "production"
          ? "We are encountering a temporary service issue. Please check back shortly or retry."
          : (error?.message || "An unexpected error occurred.")}
      </p>
      <button
        type="button"
        data-testid="error-retry-button"
        onClick={() => reset()}
        className="px-6 py-2.5 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 transition active:scale-95"
      >
        Try Again
      </button>
    </div>
  );
}
