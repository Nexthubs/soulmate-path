# M4 Sketch Ready — RV-03 independent review

> **Current verdict:** RV-03 **PASS**, M4 **PASS — COMPLETE** after the 2026-09-27 follow-up review at the end of this file. Earlier BLOCKED verdicts below are historical snapshots.

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

## RV-03 remediation re-review — 2026-09-27, HEAD `a58f6c8`

Review-start `git status --short --branch` was clean (`## main`). Compared `1b59b6f..a58f6c8`, read `docs/handoffs/RV-03-REMEDIATION.md`, and inspected the changed service/tests. No application code or migration was changed by this reviewer.
The remediation adds no Alembic revision or ORM schema change; M-02 uses the existing `ai_generation_jobs.error_json` JSONB column.

| Original item | Independent verdict | Evidence |
|---|---|---|
| H-01 prompt-failure poison loop | **FIXED.** Prompt template/input errors and persisted-profile validation now terminate `FAILED_PERMANENT` before the provider. | `backend/app/soulmate/services/sketch_generation_service.py:517-572`; new tests at `backend/tests/test_sketch_retry_idempotency.py:634-729`; 640-test PostgreSQL run. |
| M-01 double-charge on reclaim | **Original double-charge fixed, but new High finding H-02 below.** Reclaim no longer increments `attempt`; claim does. The new budget guard can be bypassed by a late fence event. | `backend/app/soulmate/services/sketch_generation_service.py:870-884,935-960`; independent disposable-PostgreSQL probe below. |
| M-02 per-attempt history | **PARTIAL.** Normal failure→success calls now retain distinct IDs. The record is capped at 20 events and is written only after a result reaches finalization; a process death before that point still leaves a provider call without a durable request ID. Historic pre-fix calls remain unreconstructible. | `backend/app/soulmate/services/sketch_generation_service.py:111,134-146,618-628,683-695,785-804`; `backend/tests/test_sketch_retry_idempotency.py` attempt-history test; original gate job predates the fix. |
| R-01 public URL | **Product decision RESOLVED; current R2 access NOT CLOSED.** `ASSET-ACCESS-01` selects one-hour signed URLs in production. `.env:78` has an empty public prefix, and the asset API generated a signed URL with `X-Amz-Expires=3600`; a signed GET succeeded. The old public custom-domain URL for that same object also still returned 200 without a session. | `DECISIONS.md` ASSET-ACCESS-01; `backend/app/soulmate/services/object_storage_sink.py:87-125`; independent API/R2 reads, 2026-09-27. |
| R-02 webhook route | **NOT_RUN.** No server was listening on port 8000 during re-review; no new webhook authenticity/replay evidence was produced. | `lsof -nP -iTCP:8000 -sTCP:LISTEN` returned no listener. |

### H-02 — High (P1), confirmed: a late fence event bypasses the crash-loop attempt cap

- **Spec Requirement:** DEV-SPEC §11.6, SP-604 and the M4 gate require bounded retries and provider spend. The remediation's claim-time guard must stop a requeued crash-loop job after `JOB_RETRY_MAX_ATTEMPTS` real claims unless a user explicitly retries.
- **Actual Implementation:** `_claim_next_queued` terminates an over-budget QUEUED job only when the **last** history event is `reclaimed`. After reclaim, a stale worker may finish and append `fence_discarded`; the last event then changes. The next worker increments `attempt` and proceeds to the provider even though the budget is exhausted. Repeated stale/late-result cycles can exceed the configured automatic cap without a user retry.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/sketch_generation_service.py:612-628,730-748,870-884,935-960`. A reviewer-only test in a generated disposable PostgreSQL DB ran three real claim→stale-reclaim cycles, then delivered the third late result; the next claim was accepted at **attempt 4** with max attempts 3. Probe result: `1 passed`, migration round-trip PASS, generated DB removed. A separate minimal `_claim_next_queued` reproduction returned `budget_exhausted=False`, `status=PROCESSING`, `attempt_after=4`.
- **Recommended Fix:** Make eligibility depend on durable retry intent or a separate retry epoch, not the mutable last history event. Keep fence/audit events orthogonal to budget authorization. Add a regression that interleaves reclaim → late success/failure → next claim at the exact cap, and assert zero further provider calls absent explicit user retry.

### M-02 remaining limitation — Medium (P2), confirmed scope limit

- **Spec Requirement:** The remediation handoff says every provider call is reconstructible from the job row alone; DEV-SPEC §19 requires useful request tracing.
- **Actual Implementation:** `attempts` keeps only the most recent 20 events, so it is not append-only over the job lifetime. A successful provider response is recorded at phase-C completion, after fenced storage; worker death before that commit leaves no durable request ID. The normal retry test verifies three returned calls, not these loss windows.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/sketch_generation_service.py:111,134-146,583-601,636-695`; `docs/handoffs/RV-03-REMEDIATION.md` M-02 claim. No real provider crash was induced in this review.
- **Recommended Fix:** Qualify the handoff's completeness claim. If full spend attribution is required, use a separate durable attempt table or gateway records, and document the unavoidable response-to-commit crash window; test history retention at the configured hard cap.

### R-01 production access condition — Medium risk, not yet verified

The owner's production ruling is recorded in `DECISIONS.md` as `ASSET-ACCESS-01`. Clearing `OBJECT_STORAGE_PUBLIC_URL_PREFIX` successfully makes the API emit one-hour presigned URLs, but it does not revoke the R2 custom domain or previously issued permanent URLs. The current object remained anonymously readable through that domain during this re-review. Production acceptance requires evidence that its actual bucket/object has no public read path; a separate private production bucket could satisfy this, but no such production check was supplied.

### Checks personally rerun

| Check | Result / limit |
|---|---|
| `JOB_WORKER_ENABLED=false .venv/bin/python backend/scripts/test_isolated.py backend/tests -q` | **PASS 640/640**, four httpx deprecation warnings; migration upgrade/downgrade/re-upgrade PASS; disposable DB removed. |
| Reviewer-only stale/fence budget probe in a disposable PostgreSQL DB | **PASS 1/1**, proving the over-budget fourth claim. Temporary probe file removed; no provider call. |
| `npm --prefix frontend test -- --run`; `typecheck`; `lint` | **PASS 307/307; PASS; PASS**. |
| Existing paid gate session: in-process authenticated Sketch API | **200 COMPLETED**, returned a URL with `X-Amz-Signature` and `X-Amz-Expires=3600`; no generation triggered. |
| Existing R2 object | Presigned GET **200 image/png**; old public custom-domain GET **200 image/png** without a session. |

**Current gate verdict: M4 BLOCKED.** H-01 is closed; H-02 prevents acceptance of bounded retry/recovery. M-02's limited audit guarantee and R-01's production private-access proof remain open for disposition. No fresh PayPal payment, live provider retry, 12-hour wait, webhook replay, or current Figma canvas comparison was performed in this re-review.

## RV-03 final follow-up — 2026-09-27, working tree on `a58f6c8`

**Verdict: RV-03 PASS; M4 PASS.** This follow-up was implemented and reviewed by the same RV-03 reviewer after finding H-02. The original Wave 6 implementation and first remediation were independently reviewed; this last fix did not receive a separate person's review. The follow-up was reviewed as a working-tree diff before the M4 completion commit; no deployment was reviewed. No migration was added.

| Item | Final disposition | Evidence |
|---|---|---|
| H-01 — High (P1) | **CLOSED.** Invalid prompt/template/profile inputs persist a permanent failure before provider invocation. | `backend/app/soulmate/services/sketch_generation_service.py:517-572`; PostgreSQL regressions in `backend/tests/test_sketch_retry_idempotency.py`; 641-test suite below. |
| H-02 — High (P1) and M-01 | **CLOSED.** Eligibility uses `user_retry_grant_pending`, set only by an explicit retry and consumed on its next claim. A late fence event cannot create a claim; the hard attempt cap is checked regardless of audit history. Reclaim leaves the attempt count unchanged. | `backend/app/soulmate/services/sketch_generation_service.py:282-301,927-963`; `backend/tests/test_sketch_retry_idempotency.py:409-480` exercises reclaim → late result → denied over-budget claim, then an explicit retry and a second denied ungranted claim. 17/17 in the focused Sketch module; full suite PASS. |
| M-02 — Medium (P2) | **ACCEPTED LIMIT.** The 20-event truncation is removed. Committed failures, completions and returned late results retain their request IDs. A worker crash before the response is committed leaves a claimed attempt with unknown provider outcome; provider logs are needed for complete spend reconciliation. The pre-fix gate job cannot prove its older IDs from the DB. This is the documented at-least-once provider risk; bounded claims prevent an unbounded crash spend loop. | `backend/app/soulmate/services/sketch_generation_service.py:129-139,927-963`; corrected `docs/handoffs/RV-03-REMEDIATION.md` and `docs/handoffs/M4-GATE-EVIDENCE.md`. |
| R-01 — Medium access risk | **CLOSED for the current configured bucket.** Owner disabled public R2 read on 2026-09-27. Both the exact previously issued public URL and a cache-busted variant returned **403** to anonymous GET, while a one-hour presigned GET of the same persisted paid object returned **200**, 3,495,657 bytes. The authenticated asset API returned 200 COMPLETED and one-hour signed URLs; anonymous API returned 403. Production config now rejects a public prefix and the URL builder refuses it even if validation is bypassed. Future production bucket settings still require M6 verification. | `DECISIONS.md` ASSET-ACCESS-01; `backend/app/core/config.py:264-274`; `backend/app/soulmate/services/object_storage_sink.py:87-103`; `backend/tests/test_config.py:102-106`, `backend/tests/test_object_storage.py:267-270`; read-only R2/API probes, 2026-09-27. |
| R-02 — Low webhook route | **Environment note; no M4 gate defect.** This follow-up did not redeliver the gate subscription's webhook. Its payment was server-confirmed through reconciliation; M2/M3 webhook evidence is in their reviews. | `docs/handoffs/M4-GATE-EVIDENCE.md`; original R-02 finding above. |

### M4 criterion check

The existing real Sandbox payment → provider generation → R2 object → page-display run is recorded in `docs/handoffs/M4-GATE-EVIDENCE.md`. This review independently read its persisted paid Sketch: one artifact and one job for its identity, complete provider/model/prompt/input/request-ID metadata, stable storage key on repeated authenticated GETs, and the same R2 bytes through a signed URL. The prior 390px page capture and SP-607's state evidence cover display; frontend state tests and the current production build cover the implementation. The original independent review inspected Q3/Q5/Q6/Q7 mapping, DB uniqueness, fencing, authorization and migration constraints. The final retry regression covers the remaining paid-asset recovery defect.

| Current check | Result |
|---|---|
| `JOB_WORKER_ENABLED=false .venv/bin/python backend/scripts/test_isolated.py backend/tests -q` | **PASS 641/641**; PostgreSQL migration upgrade/downgrade/re-upgrade PASS; disposable DB removed. Four httpx deprecation warnings. |
| Focused config/storage/retry suite | **PASS 40/40** on disposable PostgreSQL. |
| `npm --prefix frontend test -- --run`; `typecheck`; `lint`; `build` | **PASS 307/307; PASS; PASS; PASS**. The first build failed because sandbox DNS blocked Google Fonts; the authorized rerun with network access completed. |
| Existing paid object's authenticated API and private R2 read | **PASS**: anonymous API 403; authenticated API 200 COMPLETED on two reads; one artifact/job; stable key and metadata; signed URL expiry 3600 seconds; old public origin 403; signed object 200 and 3,495,657 bytes. No generation request was made. |
| `git diff --check` | **PASS** on the authorized repair and review documentation before the M4 completion commit. |

**Evidence limits:** This final follow-up did not run a new paid Sandbox purchase, a live provider failure/retry, a real 12-hour wait, a webhook replay for the M4 subscription, or a new Figma canvas comparison. The earlier paid-flow evidence and current stored-object verification support the M4 exit criterion; tests cover failure, concurrency and authorization paths. These `NOT_RUN` items are not reported as live PASS. M6 must verify production deployment configuration and private storage independently. The `morii` bucket also stores unrelated `anima/`, `rmbg/` and root objects; disabling its public access can affect their consumers and requires an owner operational check outside this M4 gate.
