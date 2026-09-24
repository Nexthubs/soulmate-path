/**
 * Soulmate Path Frontend Error Taxonomy and API Client Error Handling (SP-005, DEV-SPEC §19).
 */

export type SoulmateErrorCode =
  | "VALIDATION_ERROR"
  | "INVALID_FLOW_STATE"
  | "PAYMENT_PENDING"
  | "LOCKED_ASSET"
  | "GENERATION_FAILED"
  | "FORBIDDEN_OWNERSHIP"
  | "NOT_FOUND"
  | "PROVIDER_UNAVAILABLE"
  | "INTERNAL_SERVER_ERROR";

export interface ApiErrorPayload {
  error_code: SoulmateErrorCode;
  message: string;
  request_id?: string;
  details?: Record<string, unknown>;
}

export class SoulmateApiError extends Error {
  readonly errorCode: SoulmateErrorCode;
  readonly requestId?: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(payload: ApiErrorPayload, status: number = 400) {
    super(payload.message);
    this.name = "SoulmateApiError";
    this.errorCode = payload.error_code;
    this.requestId = payload.request_id;
    this.status = status;
    this.details = payload.details;
  }
}

/**
 * Type guard for SoulmateApiError.
 */
export function isSoulmateApiError(err: unknown): err is SoulmateApiError {
  return err instanceof SoulmateApiError;
}

/**
 * Parses raw API response payload and HTTP status into a typed SoulmateApiError.
 */
export function parseApiError(status: number, payload: unknown): SoulmateApiError {
  if (
    payload &&
    typeof payload === "object" &&
    "error_code" in payload &&
    "message" in payload &&
    typeof (payload as { error_code: unknown }).error_code === "string" &&
    typeof (payload as { message: unknown }).message === "string"
  ) {
    const raw = payload as ApiErrorPayload;
    return new SoulmateApiError(
      {
        error_code: raw.error_code,
        message: raw.message,
        request_id: raw.request_id,
        details: raw.details,
      },
      status
    );
  }

  // Fallback for non-standard error structures (e.g. proxy or gateway error)
  return new SoulmateApiError(
    {
      error_code: status >= 500 ? "INTERNAL_SERVER_ERROR" : "VALIDATION_ERROR",
      message:
        status >= 500
          ? "Our server is temporarily having trouble. Please try again shortly."
          : "Invalid request. Please try again.",
    },
    status
  );
}

/**
 * Resolves safe user-facing message suitable for UI display.
 */
export function getSafeUserErrorMessage(err: unknown): string {
  if (isSoulmateApiError(err)) {
    switch (err.errorCode) {
      case "PAYMENT_PENDING":
        return "We’re still confirming your payment. Please wait a moment.";
      case "LOCKED_ASSET":
        return err.message || "This content will unlock according to schedule.";
      case "PROVIDER_UNAVAILABLE":
        return "Your portrait is taking a little longer than expected. Please check back shortly.";
      case "GENERATION_FAILED":
        return "Portrait generation could not be completed. Please try again later.";
      case "INVALID_FLOW_STATE":
        return "Your session has moved to another step. Returning to the current question.";
      case "NOT_FOUND":
        return "The requested session or result could not be found.";
      case "FORBIDDEN_OWNERSHIP":
        return "Access denied.";
      case "VALIDATION_ERROR":
      case "INTERNAL_SERVER_ERROR":
      default:
        return err.message || "An unexpected error occurred. Please try again.";
    }
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "An unexpected error occurred. Please try again.";
}

/**
 * Determines if an error indicates that the session is absent, expired, or forbidden (401, 403, 404),
 * meaning the client genuinely has no valid active session and may create a new one.
 * Transient server (5xx) and network transport failures return false so recovery can be retried.
 */
export function isSessionMissingError(err: unknown): boolean {
  if (isSoulmateApiError(err)) {
    return (
      err.status === 401 ||
      err.status === 403 ||
      err.status === 404 ||
      err.errorCode === "FORBIDDEN_OWNERSHIP" ||
      err.errorCode === "NOT_FOUND"
    );
  }
  return false;
}

