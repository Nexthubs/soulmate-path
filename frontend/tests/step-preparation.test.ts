import { describe, it, expect, vi } from "vitest";
import {
  createStepPreparationStore,
} from "../src/soulmate/components/flow/stepPreparation";
import type { FlowStateResponse } from "../src/soulmate/api/session";

function fakeFlowState(currentStep: string): FlowStateResponse {
  return {
    session_id: "ses_test",
    current_step: currentStep,
    step_type: "transition",
    next_step: null,
    previous_step: null,
    progress_percent: 0,
    is_quiz_completed: false,
    step_metadata: null,
  };
}

describe("SP-1104: step preparation store (batch 3 §6.1–6.2)", () => {
  it("reuses the in-flight promise so the same session+target fetches once", async () => {
    const fetcher = vi.fn(
      () =>
        new Promise<FlowStateResponse>((resolve) =>
          setTimeout(() => resolve(fakeFlowState("transition_1")), 5)
        )
    );
    const store = createStepPreparationStore(fetcher);

    const p1 = store.ensure("ses_test", "transition_1");
    const p2 = store.ensure("ses_test", "transition_1");

    expect(p1).toBe(p2); // same in-flight promise handed to both callers
    const entry = await p1;
    expect(entry.status).toBe("ready");
    expect(entry.flowState?.current_step).toBe("transition_1");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("serves a ready entry without a second request", async () => {
    const fetcher = vi.fn(async () => fakeFlowState("transition_2"));
    const store = createStepPreparationStore(fetcher);

    await store.ensure("ses_test", "transition_2");
    const again = await store.ensure("ses_test", "transition_2");

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(again.status).toBe("ready");
    expect(store.get("ses_test", "transition_2")?.status).toBe("ready");
  });

  it("keys preparations by session so a different session refetches", async () => {
    const fetcher = vi.fn(async () => fakeFlowState("transition_0"));
    const store = createStepPreparationStore(fetcher);

    await store.ensure("ses_a", "transition_0");
    await store.ensure("ses_b", "transition_0");

    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("marks errors and allows a fresh retry attempt", async () => {
    let fail = true;
    const fetcher = vi.fn(async () => {
      if (fail) throw new Error("network down");
      return fakeFlowState("transition_3");
    });
    const store = createStepPreparationStore(fetcher);

    const failed = await store.ensure("ses_test", "transition_3");
    expect(failed.status).toBe("error");
    expect(failed.error).toBe("network down");

    fail = false;
    const retried = await store.ensure("ses_test", "transition_3");
    expect(retried.status).toBe("ready");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("invalidateExcept prunes non-matching steps and keeps the confirmed one", async () => {
    const fetcher = vi.fn(async () => fakeFlowState("transition_1"));
    const store = createStepPreparationStore(fetcher);
    await store.ensure("ses_test", "transition_1");
    await store.ensure("ses_test", "transition_2");
    expect(store.size()).toBe(2);

    store.invalidateExcept("transition_1");
    expect(store.get("ses_test", "transition_1")).not.toBeNull();
    expect(store.get("ses_test", "transition_2")).toBeNull();
  });

  it("clear() drops everything when the session changes", async () => {
    const fetcher = vi.fn(async () => fakeFlowState("transition_0"));
    const store = createStepPreparationStore(fetcher);
    await store.ensure("ses_old", "transition_0");

    store.clear();
    expect(store.size()).toBe(0);
    expect(store.get("ses_old", "transition_0")).toBeNull();
  });

  it("a stale response never overwrites a newer entry for the same key", async () => {
    let resolveFirst!: (v: FlowStateResponse) => void;
    const fetcher = vi.fn(
      () =>
        new Promise<FlowStateResponse>((resolve) => {
          if (fetcher.mock.calls.length === 1) {
            resolveFirst = resolve;
          } else {
            resolve(fakeFlowState("transition_1"));
          }
        })
    );
    const store = createStepPreparationStore(fetcher);

    const first = store.ensure("ses_test", "transition_1"); // hangs until resolveFirst
    // The session changes: the store is cleared, invalidating the in-flight op.
    store.clear();
    const second = await store.ensure("ses_test", "transition_1");
    expect(second.status).toBe("ready");

    // The stale first response finally lands — it must NOT mark the (new)
    // current entry; its orphan promise resolves as an entry the consumer
    // cannot mistake for fresh data of the live key.
    resolveFirst(fakeFlowState("transition_1"));
    const orphan = await first;
    expect(orphan.status).not.toBe("ready");
    expect(store.get("ses_test", "transition_1")?.status).toBe("ready");
  });
});
