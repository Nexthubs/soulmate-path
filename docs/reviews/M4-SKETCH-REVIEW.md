# M4 Sketch Ready — RV-03 independent review

- **Target:** `main` HEAD `1b59b6fc809d537bdda0b1a2b9b444aaae6ca3cd`, 2026-09-27. Review-start `git status --short --branch` was `## main`; staged/unstaged diff was empty.
- **Scope:** SP-601–607, migration/authorization/retry/storage/display, the Wave 6 remediation, and the paid-flow evidence. This review changed no application code or migration.
- **Gate:** **BLOCKED**. SP-601–607 have DONE handoffs, but H-01 breaks the permanent-input-failure and retry/recovery contract. The other findings and evidence limits below need disposition before M4 PASS.
- **Severity:** Critical/High/Medium/Low correspond approximately to AGENTS P0/P1/P2/P2. Findings are separated from risks and missing evidence.
- **Critical:** no confirmed Critical finding in this review.

## Confirmed findings

### H-01 — High (P1): prompt errors leave a paid generation queued forever

- **Spec Requirement:** DEV-SPEC §11.6 and SP-604 require permanent invalid/input failures to terminate; §12 requires invalid prompt inputs/templates to fail before provider invocation.
- **Actual Implementation:** `_claim_and_prepare` catches only `ProfileValidationError` around `build_rendered_sketch_prompt`. `SketchPromptInputError` and `SketchPromptTemplateError` are separate `ValidationError` subclasses. Either exception rolls the claim back, keeping the job QUEUED and its attempt unchanged; the worker catches the exception and retries every poll without ever producing FAILED_PERMANENT. The Sketch page stays GENERATING.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/sketch_generation_service.py:453-484,888-904`; `backend/app/soulmate/domain/sketch_prompt.py:84-93,240-249,310-319`; `backend/tests/test_sketch_generation.py:443-462` tests a missing profile only. Independent Python check confirmed both prompt exceptions are **not** subclasses of `ProfileValidationError`.
- **Recommended Fix:** Catch prompt input/template errors in phase A and persist a terminal error under the locked transaction. Add worker tests for unknown Q3/Q5/Q6/Q7 values and missing/invalid template, asserting no provider call, terminal state, and stable attempt count.

### M-01 — Medium (P2): stale reclamation charges the same claim twice

- **Spec Requirement:** DEV-SPEC §11.6 and SP-604 require a bounded, observable attempt budget; M4 requires working retry/recovery paths.
- **Actual Implementation:** claiming increments `job.attempt`; reclaim of that already-counted stale claim increments it again. With max attempts 3, first claim → stale reclaim → second claim reaches attempt 3 after only two provider opportunities. Existing reclaim tests seed PROCESSING with attempt 0, not a realistic committed claim.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/sketch_generation_service.py:715-745,779-785`; `backend/tests/test_sketch_retry_idempotency.py:295-345`. This state path is confirmed from code; no live worker-crash experiment was run.
- **Recommended Fix:** Separate the fence epoch from provider-attempt count, or invalidate a stale claim without charging it again. Test a real claim → reclaim → re-claim sequence against the configured attempt and user-retry limits.

### M-02 — Medium (P2): provider spend cannot be reconstructed from retained request IDs

- **Spec Requirement:** DEV-SPEC §11.3/§19 requires traceable provider request IDs; the M4 evidence addendum claims every call has a durable request ID on the job/artifact.
- **Actual Implementation:** success stores only the final request ID on the artifact and clears job `error_json`. Each failure overwrites the prior error record; a fenced stale result is discarded without a durable call record. The current gate job has attempt 4 but only the final ID in the artifact, so the addendum's complete-call attribution is not independently reproducible from these rows.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/sketch_generation_service.py:514-520,562-575,651-660`; `docs/handoffs/M4-GATE-EVIDENCE.md` provider-call audit addendum; read-only gate DB check on 2026-09-27.
- **Recommended Fix:** Keep append-only per-attempt request ID/status records, including discarded fence results where feasible, and reconcile with gateway records. Qualify historic attribution that the current database cannot prove.

## Risks requiring validation

### R-01 — Medium: permanent public R2 URL bypasses session checks after disclosure

- **Spec Requirement:** DEV-SPEC §20 requires ownership checks for Soulmate resources and recommends a private bucket with signed URLs or a controlled CDN.
- **Actual Implementation:** the API checks the session before returning `image_url`, but `OBJECT_STORAGE_PUBLIC_URL_PREFIX` creates a permanent direct URL. Anyone who obtains it can read the portrait without a session. UUID keys make guessing difficult; actual URL leakage or cross-user access was not observed.
- **Evidence（路径与行号）:** `backend/app/api/soulmate/artifacts.py:99-125`; `backend/app/soulmate/services/object_storage_sink.py:87-125`; unauthenticated GET of the existing object returned 200, PNG, 3,495,657 bytes (URL omitted here).
- **Recommended Fix:** Explicitly decide whether perpetual bearer URLs meet §20 before production. Prefer private R2 with short-lived signed URLs or an ownership-checking proxy; test cross-session and leakage behavior.

### R-02 — Low: current local webhook listener cannot receive the documented WireGuard route

- **Spec Requirement:** `docs/reviews/RV-03-REVIEWER-BRIEF.md` §6 requires `0.0.0.0:8000` or the WireGuard IP for live PayPal webhook verification.
- **Actual Implementation:** `lsof` showed the current Python server listening on `127.0.0.1:8000`. The existing gate subscription now has one COMPLETED ledger row, but its `provider_event_id` is NULL and there is no matching stored webhook event; this does not prove webhook delivery for that subscription. This is an environment condition, not a Wave 6 code defect.
- **Evidence（路径与行号）:** reviewer brief §6; `backend/app/db/models/billing.py:133-155,187-223`; independent read-only `lsof`/DB checks, 2026-09-27.
- **Recommended Fix:** For a webhook acceptance run, bind the server to the reachable address, redeliver a real Sandbox event, and record verified event ID, one ledger effect, and replay behavior.

## Missing or limited real acceptance evidence

- **Fresh reviewer-run paid flow: NOT_RUN.** The implementer recorded one real Sandbox payment → generation in `docs/handoffs/M4-GATE-EVIDENCE.md`. I independently verified its current `SUBSCRIBED` session, one Sketch artifact/job, `COMPLETED` metadata (`openai`, `gpt-image-2`, `v1`, Q3/Q5/Q6/Q7 inputs), authenticated Sketch API 200 with the stored key, and R2 GET 200/PNG/3,495,657 bytes. This establishes current persistence/readability, not a new payment or the compatible gateway's actual upstream model.
- **Production 12-hour wait: NOT_RUN.** `.env:27` sets Sketch unlock to `0.003` hours. The gate record matches payment + 0.003 hours; tests pin 12 hours. Thus configured server-time arithmetic is evidenced, while a real 12-hour interval is not.
- **Live failure → user retry → recovered image: NOT_RUN.** Automated fake-provider/storage tests cover the code path; this review made no paid failure/retry call.
- **Current browser visual and live Figma canvas: NOT_RUN independently.** I inspected `docs/artifacts/figma_sketch_102_461.png` and the SP-607 handoff. No Figma file key or reproducible current 390px browser capture was available; frontend tests are not a pixel comparison.
- **Gate-subscription webhook authenticity/replay: NOT_RUN.** One completed ledger row exists, but its provider event ID is NULL and no matching stored webhook event was found. M3's separate live webhook evidence is not evidence for this subscription.

## Previous remediation re-review

| Item in reviewer brief | Verdict |
|---|---|
| Same-email second-session LOCKED view | **By design** under RECOVERY-01's 2026-09-27 owner ruling. Write-side convergence remains email-scoped; read-side isolation is session-scoped. Verified-identity recovery is deferred. |
| FAILED Retry dead button | **Fixed in code/tests:** `FAILED_RETRYABLE` under `2 × max_attempts` requeues the same job; `retry_available` controls Retry/Support UI. Live paid retry NOT_RUN. |
| COMPLETED without durable key | **Fixed in code/tests:** a nonempty sink key is required; unconfigured storage fails; live page does not substitute a sample image. Existing R2 object independently read. |
| Stale-worker overwrite | **Fixed for inspected fence path:** claim attempt is checked before fenced upload inside the row lock; stale-result test rejects upload. M-01 covers separate reclaim accounting. |

## Checks personally run

| Check | Result |
|---|---|
| `JOB_WORKER_ENABLED=false .venv/bin/python backend/scripts/test_isolated.py backend/tests -q` | **PASS 636/636**, four httpx deprecation warnings. Disposable PostgreSQL upgraded/downgraded/re-upgraded with data preserved, then removed; workers disabled to avoid paid provider calls. |
| Same isolated runner, seven Sketch test modules | **PASS 132/132**, same migration round-trip. |
| `npm --prefix frontend test -- --run` | **PASS 307/307** (25 files). |
| `npm --prefix frontend run typecheck`; `npm --prefix frontend run lint` | **PASS; PASS**. |
| DB/API/R2 read-only checks | One completed Sketch/job, job attempt 4, one completed USD 19.00 ledger row without provider event ID; authenticated asset API 200; public R2 object 200/PNG/3,495,657 bytes. |
| Schema/migration inspection | No Wave 6 Alembic/model migration. Partial unique email index and unique job key exist at `backend/alembic/versions/0001_initial_soulmate_schema.py:181-203` and `backend/app/db/models/artifact.py:110-176`; disposable PostgreSQL tests exercised head. |

## Gate disposition

**M4 BLOCKED.** Correct H-01 and add regression evidence, then resolve or explicitly accept M-01/M-02 and re-review the affected paths. This review does not claim a fresh PayPal payment, webhook replay, 12-hour wait, live provider retry, or live Figma canvas comparison. RV-03 is complete as a review; M4 acceptance is not.
