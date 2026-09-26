# M3 Gate — Independent Reviewer Brief

> **Audience:** the independent high-risk reviewer performing (a) the RV-01/RV-02 re-review of the remediation, (b) post-fix real PayPal Sandbox acceptance, and (c) the M2/M3 gate decisions.
> **Prepared:** 2026-09-26, HEAD `3a486c0` (see "Review range" below).
> **Reviewer requirements (per TASK-BREAKDOWN):** independent of the implementers; payment/webhook/entitlement expertise required for M2/M3.

## 1. Mandate — decisions you are asked to make

1. **RV-01 re-review** (schema + state machine): accept or reject the remediation of the confirmed Critical/High findings.
2. **RV-02 re-review** (payment security): same, for the security findings.
3. **Post-fix Sandbox acceptance**: the real-provider evidence listed in §5 is currently NOT_RUN; decide whether it is satisfied.
4. **M2 status**: the historical M2 PASS is superseded (`M2-PAYPAL-SANDBOX-REVIEW.md` §13). Decide PASS / CONDITIONAL_PASS / BLOCKED for the current checkpoint.
5. **M3 gate** (`M3-ENTITLEMENT-RESULT-REVIEW.md` to be produced by you): required tasks SP-501..505 are implementation-complete; the exit criterion is "12h/24h logic is server-authoritative and all result UI states testable with a fake/test clock".

## 2. Reading order

| # | Document | Why |
|---|---|---|
| 1 | `AGENTS.md` §7–9, §12 | review/evidence rules, severity |
| 2 | `TASK-BREAKDOWN.md` → M2, M3, RV-01, RV-02 blocks | gate definitions; SP-403/406/407/408 and SP-501..503 are marked REVIEW |
| 3 | `Soulmate-Path-DEV-SPEC-v1.2.md` §6.2, §9–10, §14, §20, §23 | payment semantics, schema, ownership, refunds |
| 4 | `DECISIONS.md` → PAY-AUTH-01, TIME-01, ASSET-01, PAY-01/02 | entitlement/unlock authority; PAY-01/02 remain OPEN — do not invent policy |
| 5 | `docs/reviews/RV-01-RV-02-REMEDIATION.md` | the remediation evidence you are re-reviewing (finding table + evidence index + residuals) |
| 6 | `docs/handoffs/RV-01.md`, `RV-02.md` | reviewer-side records of the findings and repairs |
| 7 | Handoff addenda (dated 2026-09-26) | `SP-403`, `SP-406`, `SP-407`, `SP-408`, `SP-501`, `SP-502`, `SP-503` (RV remediation); `SP-410` (StrictMode polling race); `SP-406`/`SP-402` (E2E-found fixes/observations) |
| 8 | `PROJECT-STATE.md` | M2 currently BLOCKED; per-task REVIEW states |

## 3. Review range and key code

- **Remediation commit:** `3a486c0` — review with `git show 3a486c0` or `git diff 81ca8ce..3a486c0`. It contains Codex's C1/H1–H5/R1 repairs plus the follow-up M7/M8 closure.
- **Round-2 frontend audit fixes:** `f7eb51d` — countdown zero bounded-retry/refresh affordance, ceil rounding, per-tick recompute + visibility recalibration, production `?fixture=true` gate, live-Retry freeze removal (see `SP-504`/`SP-505` round-2 addenda).
- **Round-3 frontend audit fixes:** `64bbf69` — manual zero-refresh now restarts the bounded retry chain (`zeroCycle` dependency); Support entry is a real affordance (external link or in-product panel), dead `#support` anchor removed. NOTE: the mounted zero-exhaustion cycle still needs your virtual-clock harness for final acceptance (SSR/pure tests + a browser support-panel check are done; see SP-504 §15).
- **Adjacent E2E fixes:** `9f53818` (ACTIVATED reconcile kwarg), `4801189` (payment-processing StrictMode polling race), `e4417df`/`81ca8ce` (handoff addenda).
- Key files: `backend/app/soulmate/services/subscription_service.py` (C1 binding, H1 earliest-transaction `activate_from_payment`, H5 `_validate_new_subscription_plan`), `webhook_service.py` (H2 savepoint/retry, H3 refund `sale_id`, H4 checkpoint usage), `payment_consistency.py` (advisory locks `payment_lock`, `apply_provider_status`, `apply_billing_count`), `status_service.py` (session-scoped reads), `alembic/versions/0004_payment_event_order.py` + `0005_legacy_session_status.py`, `backend/tests/test_payment_security_regressions.py`.
- Note: evidence line numbers inside `RV-01-RV-02-REMEDIATION.md` refer to its working-tree checkpoint and may drift.

## 4. Findings traceability (original findings → where to look)

| Finding | Verify in code | Regression test |
|---|---|---|
| C1 email-ownership (Critical) | reconcile binds only via provider `custom_id`; email fallback removed; `status_service` session-scoped | `test_payment_security_regressions.py` (binding), `test_artifact_status.py`/`test_result_api.py` ownership regressions |
| H2-audit latest-payment-as-first | `_reconcile_subscription_payments` backfills before choosing `min(paid_at)`; `activate_from_payment` corrects base and pulls `unlock_at` earlier only | regressions: earliest/concurrency/delayed-earlier |
| H2-audit unresolved SALE acked | `process_webhook`: savepoint business writes; failure → `processed_at=None` + retryable non-2xx | outage/injected-failure tests |
| H3-audit refund identity | refund resolves `sale_id`; missing sale retryable; duplicate sale cannot undo refund | parameterized refund/reversal tests |
| H4-audit stale regression | migration 0004 checkpoints + `apply_provider_status`/`apply_billing_count` monotonic rules | stale-state/billing regression tests |
| H5-audit plan bypass | `_validate_new_subscription_plan` on confirm AND unknown-sub reconcile | parameterized both-path tests |
| R1 concurrency | `payment_lock` advisory locks incl. absent rows; 6-way concurrency tests | concurrency regression tests |
| M7 status enum | writer emits `SessionStatus.SUBSCRIBED`; migration 0005 normalizes legacy `'paid'`; runner asserts round-trip | updated suites + runner assertions |
| M8 docs | M2 review §13 supersession; PROJECT-STATE BLOCKED; task REVIEW states | n/a (documentation) |

## 5. Verification commands (re-run yourself; expected results at `3a486c0`)

```bash
# Backend: disposable real PostgreSQL (creates/drops its own DB; fake provider creds enforced)
.venv/bin/python backend/scripts/test_isolated.py backend/tests -q
#   expected: 504 passed + "Migration upgrade/downgrade/re-upgrade with preserved data: PASS"

# Frontend
npm --prefix frontend test -- --run          # 290 passed
npm --prefix frontend run typecheck          # PASS
npm --prefix frontend run lint               # PASS
npm --prefix frontend run build              # PASS
```

Shared dev DB is already migrated to `0005_legacy_session_status` (`alembic -c backend/alembic.ini current`).

## 6. Post-fix Sandbox acceptance checklist (currently NOT_RUN)

Reusable infrastructure: tunnel `https://ppwebhook.giaogiao.work/api/webhooks/paypal` → Caddy (public Ubuntu) → WireGuard → Mac `:8000` (**backend must start with `--host 0.0.0.0`**); sandbox webhook `5CH43533BE9149121` verified against `GET /v1/notifications/webhooks`; start commands: backend `.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000` from repo root, frontend `npm --prefix frontend run dev`.

1. **First payment (real buyer):** quiz → email → `/soulmate/subscribe?session_id=…` → approve → confirm 200 (PROCESSING) → webhook `PAYMENT.SALE.COMPLETED` `verified=true` → ledger entry → session `SUBSCRIBED`/result → artifacts `first_payment_at +12h/+24h` → Result page countdowns match DB.
2. **Duplicate/retry:** replay the same webhook event → `duplicate`, zero business effect; a previously failed event redelivered → recovers to processed.
3. **Refund & reversal:** trigger sandbox refund/reversal for the sale → verified, ledger `refunded_at` set via `sale_id`; refund arriving before its sale → stays retryable, then completes when the sale arrives.
4. **Unbound subscription:** create a subscription without `custom_id` (omit `session_id`) → confirm 403; SALE event remains retryable (not acknowledged) — then bind via authorized recovery or discard.
5. **Same-email second session:** Result shows session-scoped LOCKED sketch (no email cross-read) — confirm this confidentiality trade-off is the accepted product behavior and, if recovery is wanted, raise a task for a verified identity/recovery flow.
6. **Out-of-order statuses:** stale SUSPENDED/ACTIVATED must not regress CANCELLED/EXPIRED or clear newer failure counts.
7. **Browser polling:** approve a fresh payment → payment-processing auto-navigates to Result on webhook confirmation (StrictMode fix).

## 7. Judgment calls reserved for you

- H6 trade-off: email uniqueness prevents duplicate generation but is not authorization — the remediation removed email-scoped artifact reads; decide whether a verified-recovery task must precede M3. A second paid session on the same email is currently UNREACHABLE (PAY-02 `blocked` policy blocks offer and server-side binding); the recovery-path decision is recorded as OPEN `RECOVERY-01` in `DECISIONS.md` and gates any PAY-02 resolution away from `blocked`.
- M7 legacy migration: `0005` rewrites `'paid'` → `'SUBSCRIBED'` (downgrade restores it); confirm the migration strategy is acceptable.
- PAY-01/PAY-02 stay OPEN; the remediation deliberately does not pick re-subscription policy.

## 8. Out of scope for M3

`REPORT-01/02` (production Report generation), Sketch generation wave (SP-601+, model target `gpt-image-2`), PAY-01/02 policy selection, SP-402 `isEligible()` blank-button polish (recorded, low priority), unbound sandbox subscription `I-6EFWGVGPY6Y2` (dashboard cleanup), dashboard "Send test" events failing official verification (PayPal simulated-event quirk).

## 9. Your output

1. Re-review verdicts appended to `docs/handoffs/RV-01.md` / `RV-02.md`.
2. Sandbox acceptance evidence appended to the RV remediation doc or a new acceptance review.
3. `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` with PASS / CONDITIONAL_PASS / BLOCKED and an updated `PROJECT-STATE.md`.
