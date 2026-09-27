# WAVE 6 Review Remediation — Codex review of SP-601..607 (2026-09-26)

- **Status:** DONE
- **Scope:** verification + fixes for the Codex whole-wave review findings (3 confirmed defects fixed, 1 real race hardened, 1 product decision surfaced).
- **Branch/commit:** `main` (predecessor `57ad03b`)

## Verification verdicts and fixes

### 1. SP-606 — second same-email paid session cannot display the existing sketch — VERIFIED AS DESCRIBED; DECISION-GOVERNED (not fixed in code)
- Verified: writes converge identity-wide; reads are session-scoped, so a second session's view is LOCKED with no unlock time.
- This is the explicit, current intent of **RECOVERY-01 (OPEN)**: "Isolation is intentional; the recovery path is the open product question" and "Do NOT restore bare-email cross-session reads." Under PAY-02 `blocked`, a second paid session is unreachable through our offer/confirm paths (`_validate_new_subscription_plan`); the residual reachability is a crafted direct-PayPal subscription (documented reachability boundary), whose payment stays unbound.
- Disposition: requires the product owner's RECOVERY-01 choice (verified-identity recovery / pre-purchase block / separate purchasable asset). Presented to the product owner 2026-09-26. No unilateral code change (AGENTS.md §3/§5: do not resolve open decisions by guessing).

### 2. SP-607 — FAILED page "Retry Generation" was a dead button — VERIFIED, FIXED
- Cause: enqueue converged on ANY existing job (including terminal) and the worker only claims QUEUED, so terminal jobs could never retry.
- Fix (bounded user retry, §10.3 "Retry/Support"):
  - `enqueue_sketch_generation` now requeues a terminal job **in place** when (and only when) it is `FAILED_RETRYABLE` and its consumed attempts are under the hard cap `2 × JOB_RETRY_MAX_ATTEMPTS` (same job record, §11.5 "使用同一 artifact/job 记录 retry"; artifact returns to QUEUED → §10.3 GENERATING). `error_json` records `user_retry: true`.
  - `FAILED_PERMANENT` and over-cap jobs are never requeued — support path.
  - `GET /artifacts/sketch` gained `retry_available` (True/False/None) so the UI can split Retry vs Support honestly.
  - Frontend: `SketchViewer.retryAvailable` prop — Retry CTA hidden and a support note shown when not retryable; the live page wires it from the API. Each user retry buys exactly one provider attempt (claim consumes an attempt; a further transient failure re-terminates immediately under the cap).
- Tests: reset-in-place, cap refusal, permanent untouched, endpoint roundtrip (POST → QUEUED/GENERATING), asset API `retry_available` matrix, viewer Retry/Support rendering.

### 3. SP-605/607 — COMPLETED without a persisted image was reachable — VERIFIED, FIXED
- Cause: the unconfigured-storage fallback sink dropped bytes, returned no key, and the worker still wrote COMPLETED (`storage_key=None`); the live page even fell back to a static sample image.
- Fix:
  - **A COMPLETED artifact without a non-empty storage key is structurally impossible**: the sink contract now returns a required key; `LoggingSketchResultSink` (storage unconfigured) raises `SketchStorageUnavailableError` (permanent) → job `FAILED_PERMANENT` with `error_code=STORAGE_NOT_CONFIGURED`, artifact FAILED. No provider re-spend loops (permanent classification).
  - Storage upload/validation failures inside the fenced section classify via the same bounded budget (`STORAGE_ERROR`, retryable while attempts remain).
  - Frontend: live `durableUrl` comes only from `image_url` — the sample-image fallback was removed; a COMPLETED status without a display URL degrades to the support state (defense-in-depth).
- Tests: keyless sink → FAILED_PERMANENT + STORAGE_NOT_CONFIGURED; upload failure → bounded requeue with artifact PROCESSING; frontend rendering tests.

### 4. SP-604/605 — stale-reclaim / late-worker race (object overwrite + metadata mismatch) — VERIFIED REAL (low probability), FIXED
- Verified: the old fence checked only `status == PROCESSING`; after a reclaim + re-claim the status is PROCESSING again, so the stale worker passed the fence — and because the upload ran in phase B (before the fence), both workers could `put_object` the same deterministic §11.7 key, leaving object bytes from one result and §11.3 metadata from the other.
- Fix (fencing + single fenced upload):
  - **Claim consumes the attempt at claim time** (`job.attempt` pre-incremented on claim) — the attempt number IS the fence token.
  - Phase C finalizes only when `status == PROCESSING AND job.attempt == claim_attempt`; a reclaimed (attempt bumped) or superseded claim can never commit — neither success nor failure reports.
  - **The durable upload moved INSIDE the fenced phase-C transaction** (after the fence, before any success write). A discarded late worker never touches storage, so the object can never be overwritten by a non-surviving attempt; the committed metadata always matches the uploaded object. Upload failure falls into the same-txn bounded failure path (no COMPLETED without a key — issue 3 hardened by construction).
  - Reclaim still consumes an attempt (bounded crash loops) and now automatically invalidates the stale worker's token.
- Tests: fenced-finalize discard test (stale worker → fence mismatch, `sink` never called; surviving claim uploads exactly once and metadata matches its own result), plus the full pre-existing retry/reclaim matrix re-verified under the new accounting.

## Verification evidence
| Command/test | Result | Notes |
|---|---|---|
| `pytest backend/tests -q` | PASS (636/636) | incl. 13 new/rewritten remediation tests; backend stopped during runs (live uvicorn workers race shared-DB tests) |
| `npm --prefix frontend test -- --run` | PASS (307/307) | incl. Retry/Support split tests |
| `npm --prefix frontend run typecheck` / `lint` | PASS / PASS | |
| Backend lint/typecheck | NOT_RUN | no ruff/mypy configured; pytest is the sole backend gate |

## Files changed
| Path/module | Change |
|---|---|
| `backend/app/soulmate/services/sketch_generation_service.py` | claim-fence (attempt-at-claim), fenced phase-C upload, mandatory storage key, bounded user retry, `_write_failure_locked` consolidation |
| `backend/app/soulmate/services/object_storage_sink.py` | `SketchStorageError.permanent` + `SketchStorageUnavailableError` |
| `backend/app/api/soulmate/artifacts.py` + `schema.py` | `retry_available` on the sketch asset response |
| `backend/tests/test_sketch_retry_idempotency.py`, `test_sketch_asset_api.py` | new/rewritten tests |
| `frontend/src/soulmate/api/sketch.ts`, `components/sketch/*`, `app/soulmate/sketch/page.tsx`, `tests/sketch-live.test.tsx` | retry_available plumbing, Retry/Support split, sample-fallback removal |

## Impact on prior handoffs
- SP-604: bounded user retry supersedes "terminal jobs need manual requeue" (automatic path now exists for FAILED_RETRYABLE under the cap; FAILED_PERMANENT stays support-only).
- SP-605: the unconfigured-storage dev fallback no longer fakes completion.
- SP-606/607: response semantics extended with `retry_available`; page behavior unchanged otherwise.

---
**Paid-flow addendum:** during the live M4 gate run, the sink format gate was refined to store payloads under the SNIFFED magic-byte format (compatible endpoints may ignore `output_format`); unknown payloads still rejected. See `docs/handoffs/M4-GATE-EVIDENCE.md`.
