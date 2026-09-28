/**
 * Instrumentation coverage contract (DEV-SPEC §18, SP-901).
 *
 * Pins each client-side §18.1 event to the module(s) that emit it, so a
 * refactor that drops a tracking call fails loudly instead of silently
 * deflating the funnel. Backend-emitted events
 * (payment_confirmed, sketch_generation_*) are owned by the backend suite.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const SRC = path.resolve(__dirname, "../src");

const INSTRUMENTATION_MAP: Record<string, string[]> = {
  soulmate_landing_view: ["soulmate/components/landing/SoulmateLandingPage.tsx"],
  soulmate_start_click: ["soulmate/components/landing/SoulmateLandingPage.tsx"],
  soulmate_login_click: ["soulmate/components/landing/SoulmateLandingPage.tsx"],
  soulmate_transition_view: ["app/soulmate/loading/page.tsx"],
  soulmate_transition_continue: ["app/soulmate/loading/page.tsx"],
  soulmate_quiz_started: ["app/soulmate/quiz/page.tsx"],
  soulmate_question_view: ["app/soulmate/quiz/page.tsx"],
  soulmate_question_answered: ["app/soulmate/quiz/page.tsx"],
  soulmate_quiz_back: ["app/soulmate/quiz/page.tsx"],
  soulmate_quiz_completed: ["app/soulmate/quiz/page.tsx"],
  soulmate_interstitial_answered: ["app/soulmate/loading/page.tsx"],
  soulmate_email_view: ["app/soulmate/email/page.tsx"],
  soulmate_email_submitted: ["app/soulmate/email/page.tsx"],
  soulmate_subscribe_view: ["app/soulmate/subscribe/page.tsx"],
  soulmate_paypal_start: ["soulmate/components/subscribe/PayPalSubscriptionButton.tsx"],
  soulmate_paypal_approved: ["app/soulmate/subscribe/page.tsx"],
  soulmate_payment_failed: ["app/soulmate/payment-processing/page.tsx"],
  soulmate_result_view: ["app/soulmate/result/page.tsx"],
  soulmate_sketch_viewed: ["app/soulmate/sketch/page.tsx"],
  soulmate_report_viewed: ["app/soulmate/report/page.tsx"],
  soulmate_subscription_cancelled: [
    "soulmate/components/settings/SubscriptionSettingsAction.tsx",
  ],
};

// Unlock events emit through the shared dedupe helper (`trackArtifactUnlocked`)
// from every module that can render the unlocked state first.
const UNLOCK_HELPER_CALLS: Record<string, string[]> = {
  sketch_unlocked: [
    "app/soulmate/result/page.tsx",
    "app/soulmate/sketch/page.tsx",
  ],
  report_unlocked: [
    "app/soulmate/result/page.tsx",
    "app/soulmate/report/page.tsx",
  ],
};

const SESSION_VIEW_CALLS: Record<string, { file: string; sessionId: string; refName: string }[]> = {
  soulmate_result_view: [
    {
      file: "app/soulmate/result/page.tsx",
      sessionId: "liveData.session_id",
      refName: "resultViewTrackedSessionsRef",
    },
  ],
  soulmate_sketch_viewed: [
    {
      file: "app/soulmate/sketch/page.tsx",
      sessionId: "sketchData.session_id",
      refName: "sketchViewTrackedSessionsRef",
    },
  ],
  soulmate_report_viewed: [
    {
      file: "app/soulmate/report/page.tsx",
      sessionId: "reportData.session_id",
      refName: "reportViewTrackedSessionsRef",
    },
  ],
};

describe("client-side §18.1 instrumentation coverage", () => {
  it("every client-side event name occurs in its owning instrumented module(s)", () => {
    const missing: string[] = [];
    for (const [event, files] of Object.entries(INSTRUMENTATION_MAP)) {
      for (const file of files) {
        const source = readFileSync(path.join(SRC, file), "utf8");
        if (!source.includes(`"${event}"`)) {
          missing.push(`${event} @ ${file}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("unlock events route through the shared dedupe helper from every first-view module", () => {
    const missing: string[] = [];
    for (const [kind, files] of Object.entries(UNLOCK_HELPER_CALLS)) {
      for (const file of files) {
        const source = readFileSync(path.join(SRC, file), "utf8");
        const expectedCall = file === "app/soulmate/result/page.tsx"
          ? "trackResultArtifactUnlocks("
          : `trackArtifactUnlocked("${kind.split("_")[0]}"`;
        if (!source.includes(expectedCall)) {
          missing.push(`${kind} @ ${file}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("keys Result, Sketch, and Report views by the authorized session response", () => {
    const missing: string[] = [];
    for (const [event, callSites] of Object.entries(SESSION_VIEW_CALLS)) {
      for (const { file, sessionId, refName } of callSites) {
        const source = readFileSync(path.join(SRC, file), "utf8");
        const eventStart = source.indexOf(`name: "${event}"`);
        const callStart = source.lastIndexOf("trackSessionViewOnce(", eventStart);
        const callEnd = source.indexOf(");", eventStart);
        const eventCall = callStart >= 0 && callEnd >= 0
          ? source.slice(callStart, callEnd + 2)
          : "";
        if (!eventCall.includes(`${refName}.current`) || !eventCall.includes(`${sessionId}`)) {
          missing.push(`${event} is not keyed by an in-memory mount ref and authorized ID @ ${file}`);
        }
        if (!source.includes(`const ${refName} = React.useRef(new Set<string>());`)) {
          missing.push(`${event} does not create fresh dedupe state per component mount @ ${file}`);
        }
      }
    }
    const sketchApi = readFileSync(path.join(SRC, "soulmate/api/sketch.ts"), "utf8");
    const sketchPage = readFileSync(path.join(SRC, "app/soulmate/sketch/page.tsx"), "utf8");
    if (!sketchApi.includes("artifact_version?: string | null") ||
        !sketchPage.includes("artifact_version: sketchData.artifact_version")) {
      missing.push("Sketch view does not send the persisted artifact version");
    }
    expect(missing).toEqual([]);
  });
});
