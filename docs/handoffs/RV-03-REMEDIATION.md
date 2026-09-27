# RV-03 Remediation — M4-SKETCH-REVIEW findings (2026-09-27)

- **Status:** FOLLOW-UP FIX COMPLETE (H-02 and production signed-URL guard added 2026-09-27; M4 gate verdict belongs to `docs/reviews/M4-SKETCH-REVIEW.md`)
- **Review target:** `docs/reviews/M4-SKETCH-REVIEW.md` (RV-03, HEAD `1b59b6f`)
- **Remediation range:** working tree on `1b59b6f` + this change set

## H-01 (High, P1) — prompt errors left a paid generation queued forever — FIXED

- **Verification:** confirmed. `SketchPromptTemplateError`/`SketchPromptInputError` (and pydantic's `ValidationError` from `SoulmateProfileV1.model_validate`) are not `ProfileValidationError` subclasses; any of them escaped `_claim_and_prepare`, rolled the claim back, and the worker re-claimed the same job every poll — an unbounded poison-poll loop with the page stuck GENERATING.
- **Fix** (`backend/app/soulmate/services/sketch_generation_service.py`):
  - The profile DB read moved OUTSIDE the classification boundary (a transient DB error keeps its rollback-and-retry semantics).
  - Everything from profile materialization to the rendered prompt is now a deterministic, in-process section: `ProfileValidationError` → terminal (`VALIDATION_ERROR`); `SketchPromptTemplateError` → terminal `PROMPT_TEMPLATE_INVALID`; `SketchPromptInputError` → terminal `PROMPT_INPUT_INVALID`; pydantic `ValidationError` → terminal `PROFILE_INVALID`; any other non-I/O failure → terminal `PROMPT_BUILD_FAILED`. All persist `FAILED_PERMANENT` + artifact FAILED under the locked phase-A transaction (§11.6/§12: invalid inputs/templates fail before provider invocation).
- **Regression tests** (`test_sketch_retry_idempotency.py`): missing template version (`v999`) → FAILED_PERMANENT, `provider.calls == 0`, attempt charged once, job never re-claimed; unmapped persisted option code (`martian`) → FAILED_PERMANENT `PROMPT_INPUT_INVALID`; corrupted profile row (violating Literal field) → FAILED_PERMANENT `PROFILE_INVALID`.

## M-01 (Medium, P2) — stale reclamation charged the same claim twice — FIXED

- **Verification:** confirmed. Claim charged an attempt (as the fence token); reclaim of that already-charged stale claim charged a second; one crashed logical attempt consumed two budget slots, and the pre-existing reclaim tests seeded PROCESSING with attempt 0 (not a realistic committed claim).
- **Fix:**
  - **Reclaim no longer charges** — it requeues (QUEUED + backoff) and records a `reclaimed` event without touching `job.attempt` or `artifact.attempt_count`. The stale worker's fence is still invalidated by the NEXT claim's attempt bump.
  - **Budget enforcement moved to claim time:** when every automatic slot has been consumed by real claims (`attempt >= job_retry_max_attempts`), the next claim terminates it `FAILED_RETRYABLE` / `ATTEMPT_BUDGET_EXHAUSTED` **without** granting another provider opportunity or charging again. A later fence/audit event cannot change eligibility. An explicit user retry stores a one-claim grant, which is consumed atomically on claim; the hard `2×max_attempts` cap remains absolute.
  - Net semantics: **charges == claims**, each claim ≤ 1 provider call.
- **Regression tests:** `test_stale_claims_are_reclaimed_without_double_charging` (real claim → reclaim → zombie fence-discard → re-claim: attempts == 2 for 2 claims, full event timeline asserted); `test_crash_loop_budget_enforced_at_claim_time` (N crash cycles → next claim terminalizes, `provider.calls == 0`, charges == claims == max_attempts, `ATTEMPT_BUDGET_EXHAUSTED` on job + artifact).

## M-02 (Medium, P2) — provider spend not reconstructible from retained request IDs — FIXED

- **Verification:** confirmed. Success cleared `job.error_json`; each failure overwrote the previous record; the gate job's attempt 4 left only the final ID — the complete-call attribution in the M4-GATE-EVIDENCE addendum was not reproducible from the rows.
- **Fix:** an `attempts` history on `job.error_json`, recorded at every lifecycle point: `claimed` (per claim), `failed` (per committed failure with its own `provider_request_id`/`error_code`/`provider_code`), `completed` (winning call + storage key), `reclaimed`, `fence_discarded` (late returned results, including their request IDs), `user_retry`, and `budget_exhausted`. The initial 20-entry truncation was removed in the follow-up. Top-level error fields keep their existing latest-outcome semantics; the artifact carries the winning request ID. **Limit:** a worker that dies after a provider response but before the database commit cannot retain that response's request ID. Its claim remains recorded with an unknown outcome; provider-side logs are needed for full spend attribution. Historic gate-job attribution is implementer-recorded because pre-fix rows retained only the final ID.
- **Regression test:** `test_attempt_history_records_every_provider_call` — 2 transient failures then success → history `[claimed, failed, claimed, failed, claimed, completed]` with three distinct retained request ids, the last matching the artifact.

## R-01 (Medium) — public R2 URL — PRODUCT RULING REQUESTED (not a code change)

The API gates `image_url` behind session auth, but the `OBJECT_STORAGE_PUBLIC_URL_PREFIX` yields a permanent bearer URL readable without a session. Decision needed before production (§20): (i) accept permanent URLs on unguessable UUID keys for V1, or (ii) run production presigned-only (leave the prefix empty; 1-hour signed URLs; no code change — config only). Presented to the product owner; recorded here for the re-review.

## R-02 (Low) — environment

Accepted as an environment condition: the re-review's webhook acceptance run must bind the backend to the WireGuard-reachable interface (`--host 0.0.0.0 --port 8000`, per RV-03-REVIEWER-BRIEF §6) so Caddy can deliver; the gate subscription `I-1MLXFUCUGGB7`'s SALE event can then be redelivered to verify authenticity + one-ledger-effect + replay idempotency (its current single ledger row came via the confirm/reconcile path with `provider_event_id` NULL, as the reviewer noted).

## Verification (this remediation)

| Check | Result |
|---|---|
| `backend/scripts/test_isolated.py backend/tests -q` (disposable PostgreSQL, workers disabled) | **PASS 640/640** (636 + 3 H-01 + 1 M-02 new; 2 stale-reclaim tests rewritten for the corrected semantics) |
| Frontend `test --run` / `typecheck` / `lint` | 307/307 / PASS / PASS |
| Not re-run (unchanged scope): live paid flow, webhook replay, 12h wait, Figma canvas | NOT_RUN — reviewer's list stands |

## Follow-up after independent RV-03 re-review — 2026-09-27

- **H-02 (High, P1) fixed:** claim authorization now reads a durable `user_retry_grant_pending` flag, not the last audit event. An explicit Retry sets it; the next claim consumes it. Claims past the automatic budget without a pending grant, or past the absolute hard cap, terminate before the provider. Regression interleaves three claim → stale-reclaim cycles, a late success/fence event, a denied fourth automatic claim, an explicit user Retry, then another stale-reclaim/late result and denied ungranted claim. `test_sketch_retry_idempotency.py`: 17/17; full disposable PostgreSQL suite: 640/640, migration round-trip PASS.
- **M-02 audit limit corrected:** removed the 20-event truncation. Committed provider outcomes and late returned results retain request IDs; a response lost before DB commit cannot be reconstructed from the job row. The original gate-job request history predates this change, so its older call attribution remains unverified against durable rows.
- **ASSET-ACCESS-01 enforced in code:** production validation rejects a nonempty `OBJECT_STORAGE_PUBLIC_URL_PREFIX`; URL resolution also refuses the public-prefix path in production. `test_config.py`, `test_object_storage.py`, and Sketch retry regression: 40/40 on disposable PostgreSQL. On the existing paid Sketch object, after the owner disabled public R2 access, both the exact old public URL and a cache-busted variant returned 403; the one-hour presigned GET returned 200 with 3,495,657 bytes. The authenticated Sketch API returned 200 COMPLETED, the same storage key on two reads, and one-hour signed URLs; anonymous API returned 403. This verifies the present dev bucket, not a future production deployment.
- **Final checks:** full disposable PostgreSQL suite 641/641 plus migration round-trip; frontend 307/307, typecheck, lint and production build PASS. `git diff --check` PASS before the M4 completion commit.

## Files changed

| Path | Change |
|---|---|
| `backend/app/soulmate/services/sketch_generation_service.py` | H-01 classified terminal section; M-01 no-charge reclaim + claim-time budget terminal; M-02 attempts history + event recording at all lifecycle points |
| `backend/tests/test_sketch_retry_idempotency.py` | 2 rewritten + 4 new tests |
| `backend/tests/test_sketch_provider.py` | hermetic image-format pinning (real `.env` now sets png) |
