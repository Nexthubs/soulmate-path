/**
 * Domain types and props for Sketch Viewer (DEV-SPEC §2, §10.3, §11; DECISIONS ASSET-01, DOMAIN-01).
 */

export type SketchViewState = "ready" | "loading" | "completed" | "failed";

export interface SketchViewerProps {
  /**
   * Current visual state of the sketch viewer.
   */
  state?: SketchViewState;

  /**
   * Project-owned durable asset URL for the completed portrait (ASSET-01).
   */
  durableUrl?: string;

  /**
   * Heading title. Defaults to "Your Personal Soulmate Insights" (Figma 102:462).
   */
  title?: string;

  /**
   * Configurable back navigation destination (defaults to SOULMATE_ROUTES.RESULT, no hardcoded domain).
   */
  backUrl?: string;

  /**
   * Custom back action callback.
   */
  onBack?: () => void;

  /**
   * Callback fired when user clicks Retry on failed state.
   */
  onRetry?: () => void;

  /**
   * Callback fired when user clicks "Generate My Sketch" on the ready state
   * (UNLOCKED + NOT_STARTED, §10.3). The caller invokes the idempotent
   * generation trigger; the viewer only renders state.
   */
  onCheckNow?: () => void;

  /**
   * While a triggered generation request is in flight (disables the ready CTA).
   */
  isTriggering?: boolean;

  /**
   * Whether to show the fixture preview switcher for QA/dev.
   */
  showFixtureToolbar?: boolean;

  /**
   * Partner gender description or summary tag.
   */
  partnerGender?: string;

  /**
   * Error message displayed when state is "failed".
   */
  errorMessage?: string;

  /**
   * Additional container CSS classes.
   */
  className?: string;
}
