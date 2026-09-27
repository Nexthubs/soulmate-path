# M4 Gate Evidence — Live paid-flow generation (2026-09-26/27)

- **Scope:** one real PayPal sandbox paid flow end-to-end against the deployment's real integrations (OpenAI-compatible `gpt-image-2` endpoint + Cloudflare R2), executed by the product owner (payment) and agent (funnel driving, verification).
- **Environment:** local dev; `SOULMATE_SKETCH_UNLOCK_HOURS=0.003` (≈11s, gate-only; production keeps 12).

## Evidence chain (all timestamps UTC)

| Step | Evidence |
|---|---|
| Quiz funnel (17 questions + 3 interstitials) | driven via browser automation; session `ses_03e65a2e69403d7a6c4148978fa1cd54`, email `m4gate.1790440508872@example.com` |
| Email capture | bound server-side (email_normalized identity) |
| Subscribe offer | intro $19.00 / regular $29.00 (PAY-01 placeholder prices as configured) |
| PayPal subscription created **with session binding** | `I-1MLXFUCUGGB7`, `custom_id=ses_03e6…` (first attempt `I-FGSSDH3FVCGK` exposed the missing-binding defect below; cancelled at PayPal, status CANCELLED) |
| Server confirmation (PAY-AUTH-01) | session → `SUBSCRIBED`, `subscription_success_at=2026-09-26T16:59:16Z` (provider/server-confirmed, not client approval) |
| Artifact placeholders (SP-501) | SKETCH unlock `16:59:26.8Z` (= payment + 0.003h ✓), REPORT unlock `+24h ✓`, one row each |
| Sketch page state (§10.3) | LOCKED→READY after unlock; READY rendered "Generate My Sketch" CTA |
| Trigger (§11.4 on_demand) | POST generate → job `52c4f078…` QUEUED; page GENERATING with bounded polling |
| Provider call (§11/§25) | real compatible-endpoint calls captured: `aec45aff…`, `e27554ea…`, `b3980150-8edb-4bff-9e42-0b8b1fa8703c` (final) — model `gpt-image-2` |
| Durable persistence (ASSET-01/§11.7) | R2 object `soulmate/sketches/e2ee07b7…/original.png` — public URL GET **200, 3,495,657 bytes, content-type image/png** |
| §11.3 metadata on artifact | provider=openai, model=gpt-image-2, prompt_version=v1, input_json `{gender: male, age_range: 20-30, ethnicity: Caucasian/White, features: Kindness}` (matches quiz answers Q3/Q5/Q6/Q7 exactly), provider_request_id stored |
| Page displays persisted asset | 390px screenshot: real pencil-sketch portrait rendered from the R2 URL; Save Image / View Report present |
| Refresh invariance | reload → same storage key, API COMPLETED, portrait shown; no second job created (one logical generation per identity) |

## Real defects found and fixed during the run

1. **P1 — email→subscribe lost `session_id`** → PayPal subscription created without `custom_id`; server confirm correctly rejected it (PAY-AUTH-01 held). Fixed in three layers (email page carries the param; subscribe page resolves the cookie session as fallback; button refuses to render checkout without a session binding). The orphaned live subscription was cancelled at PayPal.
2. **PayPal SDK `render()` rejection was silently swallowed** (blank checkout area, `paypal_js_sdk_v5_unhandled_exception`) — fixed with explicit catch + one retry + surfaced error.
3. **Compatible endpoint ignores `output_format=webp` and returns PNG** — the sink's format gate rejected valid images. Fixed: the sink now stores under the **sniffed** magic-byte format (reclassification, never a lying extension); unknown payloads are still rejected.
4. **Ops — duplicate uvicorn processes**: an older server instance kept claiming jobs with pre-fix code. Cleaned; single-instance confirmed. Reminder recorded: never run pytest with a live server up.
5. **Test hermeticity — unlock hours**: the suite assumed 12h/24h defaults while the dev `.env` legitimately holds 0.003h; new `backend/tests/conftest.py` pins spec defaults for all tests (suite green regardless of developer `.env`).

## Verification summary

| Check | Result |
|---|---|
| Backend suite (with conftest hermeticity) | PASS 636/636 |
| Frontend suite / typecheck / lint | PASS 307/307 / PASS / PASS |
| Live paid flow → confirmation → entitlement → artifacts | PASS (chain above) |
| Live generation → durable storage → page display | PASS (chain above) |
| Payment ledger (webhook path) | NOT_RUN — no local webhook tunnel in this run; subscription activation came via server-confirmed reconciliation path (SP-408); webhook receipt evidence exists from M3 live acceptance (I-1GHJRE2NM8K2). Ledger row for this new subscription will land when the sandbox event reaches a configured webhook endpoint. |
| Refund/cancel of THIS subscription | NOT_RUN (intentionally left active for re-verification of revisit flows; cancel paths have live evidence from M3) |

## Disposition

The M4 "Sketch Ready" exit criteria are now evidenced end-to-end with real money-flow and real provider/storage integrations. Remaining for the M4 review artifact: independent reviewer pass over the handoffs (SP-601..607 + WAVE6-REVIEW-FIXES + this evidence doc).

## Addendum — provider-call audit (2026-09-27, product-owner observation)

The owner observed 8 gateway consumption rows for `gpt-image-2` and questioned the request policy. Full audit against our DB (every provider call leaves a `provider_request_id` on the job/artifact):

| Gateway row (local) | Attribution | Request id |
|---|---|---|
| 11:00:14 (in 1410 / out 3168) | **Real gate-run success** (attempt 4 after in-run fixes) | `b3980150…` |
| 11:11:15 / 11:11:57 / 11:13:01 / 11:15:06 (in 1394 / out 3168) | **Test-suite drain**: the live backend's lifespan workers claimed jobs enqueued by the backend test suite executed while the server was up — a process-hygiene violation of our own documented rule ("never run pytest with a live server"), not a product defect | `ce03ccde…`, `59a85b4b…`, `408e892f…`, `7ca7a63b…` |
| 11:11:21 / 11:13:05 / 11:15:00 (in 697 / out ~166) | **Not ours**: no matching `provider_request_id` exists in our DB; our adapter makes exactly one POST per attempt, so no code path emits a second smaller call. Occurring seconds after each completion, these are most plausibly gateway-internal rows (e.g. moderation/metadata pass or upstream retry) or unrelated traffic on the shared token — owner can expand a row to inspect the prompt | — |

Also accounted: the real gate generation's earlier 3 attempts (format-gate failures under the old sink code, ~09:02–09:05 local, request ids `aec45aff…`/`e27554ea…` + one overwritten) predate the screenshot's visible window — total real spend for the user generation = 4 calls across its defect-fixing lifetime, 1 per attempt per the §11.6 retry budget.

**Remediation:**
- Dev DB purged: 150 leftover test jobs + 2053 test artifacts deleted; only the gate session's COMPLETED job/artifact remain. The ~136 stale QUEUED garbage jobs (which would fail cheaply in phase A without provider calls but pollute the queue) are gone.
- Re-verified after cleanup: worker silent (no new calls), gate artifact/R2 object/API all intact.
- Standing rule re-confirmed and now practiced: the backend must be stopped (or `JOB_WORKER_ENABLED=false`) before running the backend test suite; durable-queue drain-on-start is correct production behavior but burns real tokens on shared-dev-DB test data.
- Pair spacing (<10s) explained: `JOB_WORKER_CONCURRENCY=4` workers poll simultaneously and claim different jobs within milliseconds when multiple are QUEUED.
