# M4 Gate — Independent Reviewer Brief (RV-03: Sketch generation correctness)

> **Audience:** the independent reviewer (Codex) performing the RV-03 correctness review of the Sketch generation wave (SP-601..607), the re-review of the Codex whole-wave findings and their remediation, and the M4 gate decision.
> **Prepared:** 2026-09-27, HEAD `ed5371d` (review range in §3).
> **Reviewer requirements (per AGENTS.md §8):** independent of the implementers; concurrency/durability/identity expertise relevant for generation correctness and asset durability.

## 1. Mandate — decisions you are asked to make

1. **Wave 6 correctness review** (SP-601..607): the prompt/template contract, provider isolation, queue/worker correctness (idempotency, fencing, bounded retries, stale reclamation), durable persistence, identity-level dedup, and page states — accept or raise findings.
2. **Remediation re-review**: four confirmed findings from the implementer-team's own whole-wave Codex review were fixed (fencing, durable-persistence guarantee, bounded user retry, session-binding loss). Re-verify each fix in code + tests (`docs/handoffs/WAVE6-REVIEW-FIXES.md`).
3. **Live paid-flow acceptance**: the evidence in `docs/handoffs/M4-GATE-EVIDENCE.md` (real PayPal sandbox payment → server confirm → generation via a compatible `gpt-image-2` endpoint → Cloudflare R2 → page display) is implementer-executed. Re-run what you consider load-bearing (see §6 checklist) and decide whether it satisfies the M4 exit criteria.
4. **M4 gate** (`docs/reviews/M4-SKETCH-REVIEW.md` to be produced by you): required tasks SP-601..607 are DONE. Exit criterion (TASK-BREAKDOWN M4): Sketch generation is correct, durable, idempotent, and one-per-identity, with the display path serving the persisted asset.

## 2. Reading order

| # | Document | Why |
|---|---|---|
| 1 | `AGENTS.md` §5–9, §12 | scope discipline, evidence rules, severity (P0/P1 definitions apply to your findings) |
| 2 | `TASK-BREAKDOWN.md` → Wave 6 blocks (SP-601..607) + M4 gate row | task scope/acceptance you are reviewing against |
| 3 | `Soulmate-Path-DEV-SPEC-v1.2.md` §11 (Sketch AI generation), §12 (prompt v1), §14 (schema/uniqueness), §19 (observability), §20 (identity/IDOR), §22 (config) | the contracts the wave implements |
| 4 | `DECISIONS.md` → ASSET-01, IMGPROVIDER-01, PROMPT-01, RECOVERY-01 (esp. the 2026-09-27 ruling), TIME-01, PAY-AUTH-01, PAY-02 | ASSET-01/IMGPROVIDER-01 are RESOLVED and binding; PROMPT-01 OPEN — do not reinterpret Q7; RECOVERY-01 isolation is a confirmed intentional ruling, not a finding |
| 5 | `docs/handoffs/SP-601.md` … `SP-607.md` | per-task implementation evidence + acceptance mapping |
| 6 | `docs/handoffs/WAVE6-REVIEW-FIXES.md` | the four review findings, their verification verdicts, and fixes (your re-review target) |
| 7 | `docs/handoffs/M4-GATE-EVIDENCE.md` (+ provider-call audit addendum) | the live paid-flow evidence chain and the gateway-request attribution |
| 8 | `PROJECT-STATE.md` | current milestone state |

## 3. Review range and key code

Commits (oldest → newest), HEAD `ed5371d`:

| Commit | Content |
|---|---|
| `cfaa687` | SP-601 versioned prompt template + SP-602 provider adapter |
| `60b74c7` | SP-603 queue/worker + `OPENAI_BASE_URL` compatible endpoint (IMGPROVIDER-01) |
| `db364be` | SP-604 retry/idempotency (two-phase claims, bounded backoff, stale reclamation) |
| `538a868` | SP-605 durable object storage (S3-compatible sink, boto3) |
| `338fc7d` | SP-606 one-email-one-sketch identity-level convergence |
| `57ad03b` | SP-607 live Sketch page states + `GET /artifacts/sketch` |
| `8b568ab` | **Review remediation** — claim fencing, fenced durable upload, mandatory storage key, bounded user retry, `retry_available` |
| `369c6f8` | M4 gate evidence; sink sniffed-format reclassification; `backend/tests/conftest.py` hermeticity |
| `ed5371d` | Provider-call audit addendum; dev-DB cleanup record |

Review with `git diff cfaa687^..ed5371d` or per-commit `git show`.

Key code (backend): `backend/app/soulmate/domain/sketch_prompt.py`, `domain/sketch_models.py`, `services/sketch_generation_service.py` (enqueue convergence, two-phase claim/process, fence, `_write_failure_locked`, `reclaim_stale_processing_jobs`), `services/openai_image_provider.py`, `services/object_storage_sink.py` (validation rules, `build_sketch_image_url`), `api/soulmate/artifacts.py`, `core/config.py` (§22 groups; repo-root `.env` anchoring), `main.py` (lifespan workers). Frontend: `src/soulmate/api/sketch.ts`, `hooks/useSketchStatus.ts`, `components/sketch/*`, `app/soulmate/sketch/page.tsx`, `components/subscribe/PayPalSubscriptionButton.tsx` (binding guard), `app/soulmate/email/page.tsx` (session_id propagation).

DB schema is unchanged from SP-501 (`soulmate_artifacts` incl. `uq_soulmate_one_sketch_per_email` partial unique index; `ai_generation_jobs` with unique `idempotency_key`) — **no Wave 6 migrations**; verify that claim.

## 4. Findings traceability (previous Codex findings → fixes → regressions)

| Finding | Fix to verify | Regression test |
|---|---|---|
| 1. Same-email second session cannot display existing sketch | Verified as described; ruled INTENTIONAL per RECOVERY-01 2026-09-27 update in `DECISIONS.md` — confirm you accept it as by-design, not a finding | `test_one_email_one_sketch.py` (isolation at API level), `test_sketch_generation.py` |
| 2. FAILED-page Retry was a dead button | Bounded user retry: enqueue requeues a `FAILED_RETRYABLE` terminal job in place under hard cap `2 × JOB_RETRY_MAX_ATTEMPTS`; `retry_available` on the asset API; frontend Retry/Support split | `test_sketch_retry_idempotency.py` (reset-in-place, cap refusal, permanent untouched), `test_sketch_asset_api.py` (retry_available matrix, endpoint roundtrip), `sketch-live.test.tsx` |
| 3. COMPLETED without a persisted image was reachable | Sink contract requires a non-empty key; unconfigured storage → permanent `STORAGE_NOT_CONFIGURED`; upload inside the fenced section; frontend sample-image fallback removed | `test_sketch_retry_idempotency.py` (keyless → FAILED_PERMANENT; upload failure → bounded requeue), `test_object_storage.py` |
| 4. Stale-reclaim / late-worker race (object overwrite + metadata mismatch) | `job.attempt` consumed at claim time doubles as the fence token; phase C commits only on `status==PROCESSING && attempt==claim_token`; the durable upload runs INSIDE the fenced transaction | `test_sketch_retry_idempotency.py::test_fenced_finalize_discards_stale_worker_result` + the stale-reclaim pair |

## 5. Verification commands (re-run yourself; expected at `ed5371d`)

```bash
# Backend — disposable real PostgreSQL (creates/drops its own DB; do this with the dev server STOPPED)
.venv/bin/python backend/scripts/test_isolated.py backend/tests -q
#   expected: 636 passed
# NOTE: backend/tests/conftest.py pins the §-spec unlock-hour defaults (12h/24h), so the
# suite is hermetic against the developer's real .env (currently 0.003h for gate runs).

# Frontend
npm --prefix frontend test -- --run          # 307 passed
npm --prefix frontend run typecheck          # PASS
npm --prefix frontend run lint               # PASS

# No ruff/mypy configured; pytest is the sole backend gate (recorded limitation).
```

## 6. Environment (MARKED — read before any live testing)

- **PayPal webhook path:** `https://ppwebhook.giaogiao.work/api/webhooks/paypal` → Caddy (public Ubuntu server) → **WireGuard tunnel → this Mac's WG IP `192.168.8.7` (utun11), port 8000**. Therefore the backend MUST be started listening on a WG-reachable interface — **never bare `127.0.0.1:8000`**:
  ```bash
  # from repo root (matches the M3-accepted invocation):
  .venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
  # (or --host 192.168.8.7 to bind WG only; 0.0.0.0 is the M3-precedent)
  ```
  Sandbox webhook `5CH43533BE9149121` is registered/verified at PayPal (see M3 brief §6).
- **Webhook-ledger completion opportunity:** the gate subscription `I-1MLXFUCUGGB7` was confirmed during the gate run while the backend was bound to `127.0.0.1` (Caddy could not reach it) — its `PAYMENT.SALE.COMPLETED` ledger row is the one NOT_RUN item. With the backend on `0.0.0.0`, either await PayPal's automatic retries or trigger a redelivery from the sandbox dashboard (real-event redelivery verifies; the M3 "Send test" simulation quirk does not apply), then verify: `verified=true` → exactly one `subscription_payments` row → idempotent on replay (duplicate, zero business effect).
- **Shared dev DB:** the dev PostgreSQL (`soulmate_dev`) is shared between the running server and tests. **Stop the backend (or set `JOB_WORKER_ENABLED=false`) before running the backend suite** — lifespan workers drain the queue and will race test-enqueued jobs with real provider calls (documented in M4-GATE-EVIDENCE addendum; 4 drain calls occurred exactly this way).
- **Provider endpoint:** OpenAI-compatible gateway configured via `OPENAI_BASE_URL`/`OPENAI_API_KEY` (IMGPROVIDER-01, RESOLVED); model `gpt-image-2`. **Known quirk:** the gateway ignores `output_format` and returns PNG — the sink stores under the sniffed magic-byte format (accepted deviation; judge its acceptability). Every call leaves a `provider_request_id` on the job/artifact — spend is auditable.
- **Object storage:** Cloudflare R2 (S3-compatible) via `OBJECT_STORAGE_*`; display URLs prefer the public custom-domain prefix `https://r2-morii.zhaozhao.org/…` (objects publicly readable by unguessable key — judged acceptable for V1, flagged for your review); presigned 1h URLs are the fallback for private buckets.
- **`.env` state:** `SOULMATE_SKETCH_UNLOCK_HOURS=0.003` (≈11s, gate-only). For live re-verification of the countdown either keep it (fast unlock) or set `12` and restart; the suites are unaffected (conftest pins).
- **Gate-run references:** session `ses_03e65a2e69403d7a6c4148978fa1cd54`, email `m4gate.1790440508872@example.com`, artifact `e2ee07b7…` (COMPLETED, `soulmate/sketches/e2ee07b7…/original.png`, request id `b3980150…`). A second live paid flow needs a **fresh email** (`uq_soulmate_one_sketch_per_email`).

## 7. Live acceptance checklist (re-run at your discretion)

1. **Fresh-email paid flow** (the M4 core): quiz → email → subscribe → PayPal approve → confirm 200 → `custom_id` present on the provider subscription → artifacts created (`unlock_at = payment + configured hours`) → unlock → READY → Generate → one real provider call → R2 object → page displays the persisted asset → refresh invariance (no second generation) → §11.3 metadata (prompt_version/model/input_json/provider_request_id) on the artifact.
2. **Webhook ledger completion** for `I-1MLXFUCUGGB7` (see §6) + duplicate-event idempotency.
3. **User retry path** (optional, costs one provider call): force a retryable failure (e.g. invalid `OBJECT_STORAGE_*` at runtime) → FAILED after 3 attempts → `retry_available=true` → POST generate requeues the same job → restore storage → completes. Verify no second artifact ever exists.
4. **Fence/stale behavior** is unit-tested; a live double-worker experiment is optional (costly to stage) — code review of `_claim_and_prepare`/`_finalize_*`/`reclaim_stale_processing_jobs` is the primary evidence.
5. **Generation spend audit:** every provider call must correspond to a `provider_request_id` recorded on a job/artifact (the M4-GATE-EVIDENCE addendum demonstrates the method).

## 8. Judgment calls reserved for you

- **Sink format tolerance:** storing under the sniffed format (PNG despite a webp request) vs. hard-failing. The current rule: sniffed-format reclassification, unknown formats rejected, extension never lies.
- **R2 public-prefix display URLs** (publicly readable by unguessable UUID key) vs. presigned-only — V1 accepted; whether it must gate M4 or defer to M6 hardening.
- **At-least-once provider spend** (worker death between provider success and fenced commit re-runs the call on retry): bounded by the retry budget, alerted via §19.2 — accept or require a spend-guard before M6.
- **Bounded user retry policy** (FAILED_RETRYABLE under `2×max_attempts` user-requeueable; FAILED_PERMANENT support-only) — accept or adjust the cap.
- **RECOVERY-01:** per the 2026-09-27 ruling in `DECISIONS.md`, isolation is intentional and implementation is deferred — confirm this closes the finding rather than re-raising it.
- **PROMPT-01** stays OPEN (Q7→`features` kept verbatim per PRD); note `q06=no_preference` renders as "No preference" inside the PRD's hard-constraint ethnicity slot — flagged for product in SP-601 §9, not a code fix.
- **PAY-01/PAY-02** remain OPEN; do not invent policy.

## 9. Out of scope for RV-03/M4

Report wave (SP-701+ / M5), RECOVERY-01 implementation (deferred task), PAY-01/02 selection, production pricing/deployment (M6), SP-402 `isEligible()` button polish, the three unmatched 697-token gateway rows (attributed as non-ours in the M4-GATE-EVIDENCE addendum; expandable at the gateway if you wish to double-check).

## 10. Your output

1. `docs/reviews/M4-SKETCH-REVIEW.md` with PASS / CONDITIONAL_PASS / BLOCKED, per-finding verdicts on §4, and evidence you personally re-ran (commands + results per AGENTS.md §9).
2. Any new findings as P0/P1/P2 with the severity definitions of `AGENTS.md` §12 (P1 includes duplicate Sketch despite uniqueness; lost Quiz recovery; client-clock unlock bypass).
3. Updated `PROJECT-STATE.md` (M4 row + next safe tasks).
