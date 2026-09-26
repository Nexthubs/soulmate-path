# M3 — Entitlement / Result Ready Review

- **Review result:** CONDITIONAL_PASS
- **Reviewer:** Codex (RV-01/RV-02 audit rounds 1–3, code-level acceptance) + ZCode agent session (remediation implementation, real-provider acceptance execution and evidence compilation; buyer approval and dashboard refund performed by the project owner)
- **Date:** 2026-09-26
- **Reviewed branch/commit:** main @ `f501793` (remediation `3a486c0` + round-2 `f7eb51d`/`72e7937` + round-3 `64bbf69`/`0bc8ecc`)
- **Milestone source:** `TASK-BREAKDOWN.md` → `M3`

## 1. Scope and handoffs reviewed

Required Task IDs: SP-501..505 (+ RV-01/RV-02 quality gates over the payment components).

Handoffs: `docs/handoffs/SP-501.md`–`SP-505.md` (incl. RV + E2E addenda), `docs/handoffs/RV-01.md`, `RV-02.md`, `docs/reviews/RV-01-RV-02-REMEDIATION.md`, `docs/reviews/M3-REVIEWER-BRIEF.md`.

## 2. Exit criterion

"12h/24h logic is server-authoritative and all result UI states are testable with a fake/test clock."

## 3. Current implementation evidence

- SP-501: concurrency-safe create/ensure of SKETCH/REPORT placeholders on every confirmed payment (savepoints + DB unique constraints + advisory locks); unlock base is the authoritative `first_payment_at`.
- SP-502: pure domain derivation (`availability`/`generation`/combined `status`), injectable clock, fail-closed unknown states.
- SP-503: `GET /api/soulmate/result` single aggregate with server time, 403 for anonymous/IDOR/unentitled; SP-501 self-heal on read.
- SP-504/SP-505: server-clock-offset countdown, zero-refetch with bounded retries + manual affordance, visibility recalibration, bounded GENERATING polling; preview overrides limited to non-production fixture mode.
- RV remediation (accepted by Codex code review round 3): strict `custom_id` ownership binding, earliest-transaction first-payment basis, retryable unresolved events, refund-by-`sale_id`, persisted status/billing checkpoints (migration `0004`), server-side plan policy, advisory-lock serialization. Canonical `SUBSCRIBED` status (migration `0005`).

## 4. Accepted contract checkpoint

- **API:** `GET /api/soulmate/result` (aggregate; 403 semantics); `POST /api/soulmate/subscription/{paypal/confirm,reconcile,cancel}`; `POST /api/webhooks/paypal`.
- **Types / schemas:** `ResultAggregateResponse` + `ArtifactStatusView`; nullable `unlock_at`; additive combined `status`.
- **DB migrations:** `0004_payment_event_order` (ordering checkpoints), `0005_legacy_session_status` (`'paid'` → `'SUBSCRIBED'`); applied to shared dev DB and round-trip tested in disposable PostgreSQL.
- **Configuration / provider state:** sandbox webhook `5CH43533BE9149121` verified against `GET /v1/notifications/webhooks`; tunnel `ppwebhook.giaogiao.work/api/webhooks/paypal` delivering real events; `SOULMATE_RESUBSCRIPTION_POLICY=blocked`.

## 5. Required evidence checklist

| Required evidence (TASK-BREAKDOWN M3) | Evidence |
|---|---|
| payment → artifact entitlement creation evidence | Live sandbox payment `I-1GHJRE2NM8K2` / sale `3UK11330C0943211A`: confirm bound via `custom_id`, verified `PAYMENT.SALE.COMPLETED`, ledger cycle 1, artifacts created (see §6 row 1) |
| `sketch_unlock_at = first_payment_completed_at + 12h` tests | `test_artifact_entitlement.py`, `test_artifact_status.py` + live: unlock `22:41:11Z` = `10:41:11Z` + 12h (exact) |
| `report_unlock_at = first_payment_completed_at + 24h` tests | same suites + live: `10:41:11Z` + 24h (exact) |
| client clock tampering cannot unlock content | `test_status_changes_only_through_injected_server_clock`, offset tests; availability is a server-computed field; client time never an input |
| LOCKED/READY/GENERATING/COMPLETED/FAILED coverage | `test_artifact_status.py` (pure + service), `test_result_api.py` (API level); all five states produced distinctly |
| route authorization/ownership checks | `test_result_api.py` (anonymous/IDOR/unentitled 403); custom_id-only binding verified live (unbound confirm 403, round-2 E2E) |
| test-clock scenario matrix | injectable-clock suites for SP-502/504/505 (`test_artifact_status.py`, `result-live-countdown.test.tsx`, `result-polling.test.ts`) |
| Result aggregate API contract checkpoint | SP-503 handoff; stable key sets asserted; polling schema-stability test |

## 6. Test / manual / provider evidence

| Check | Result | Evidence/notes |
|---|---|---|
| Backend isolated suite | PASS | 504/504 (`backend/scripts/test_isolated.py`, disposable PostgreSQL, migration round-trip incl. 0005) |
| Frontend suite / typecheck / lint / build | PASS | 296/296; exit 0 ×3 |
| Live first payment (post-fix) | PASS | sale `3UK11330C0943211A` $19.00; confirm bound via `custom_id`; `PAYMENT.SALE.COMPLETED` `WH-04W02002U2028950M…` verified; ledger cycle 1; artifacts +12h/+24h exact; session `SUBSCRIBED`/result; browser auto-navigated |
| Live duplicate/replay | PASS | PayPal `resend` of the payment event → verified → deduped by event id → zero business effect (ledger unchanged) |
| Live suspend/activate ordering | PASS | real `SUSPENDED` (checkpoint applied) → `ACTIVATED` → final ACTIVE, no regression |
| Live refund (sale_id resolution) | PASS | dashboard refund → two real `PAYMENT.SALE.REFUNDED` deliveries, both verified and idempotently processed; ledger `status=REFUNDED, refunded_at=10:59:59Z` via `sale_id` |
| Live cancel / paid-through | PASS | API cancel persisted `paid_through_at=2026-10-26` before provider cancel; PayPal `BILLING.SUBSCRIPTION.CANCELLED` verified; `next_billing` cleared; access-retained semantics |
| Cross-restart dedupe of a previously-acked event | PASS | pre-fix acked event resent → deduped (no re-execution) |
| Unbound-SALE stays pending (not acked) | PASS (unit) | `test_missing_binding_sale_stays_pending_even_with_unique_payer_email` + remediation suite; live path blocked at confirm (403 evidence, round-2 E2E) |
| `PAYMENT.SALE.REVERSED` live | NOT_RUN | sandbox cannot trigger a dispute/chargeback; same handler/resolve path as REFUNDED (resource-id resolution) |
| Mounted zero-exhaustion browser cycle | PASS | Codex virtual-clock harness (round-2/3 audits) reproduced and re-verified the fixed behavior; support panel browser-verified live in this session |

## 7. Findings

### P0
- none open.

### P1
- none open.

### P2
- `RECOVERY-01` (OPEN decision): same-email second paid session has no Sketch recovery path — session-scoped reads are intentional (§20); under the current `blocked` PAY-02 policy the path is unreachable server-side, but a crafted client can still be charged at PayPal without binding (refund + support are the fallback). Must resolve before PAY-02 moves away from `blocked`. This is a recorded product decision, NOT an accepted recovery feature.

## 8. Deviations / unresolved decisions

- `PAY-01`/`PAY-02`/`RECOVERY-01`/`AGE-01`/`DOMAIN-01`/`LEGAL-01` remain OPEN per `DECISIONS.md`.
- `PAYMENT.SALE.REVERSED` live trigger not possible in sandbox (see §6).
- Historical handoff claims superseded by the RV addenda are marked in place; `M2-PAYPAL-SANDBOX-REVIEW.md` §13 records the supersession.

## 9. Rollback / recovery notes

- Migrations `0004`/`0005` are additive; `0005.downgrade` restores legacy status values. Roll back application code together with the schema revision.

## 10. Conditions for pass

1. `RECOVERY-01` must be resolved (and `PAY-02` may only move away from `blocked` afterwards) before enabling re-subscription checkout.
2. First real `PAYMENT.SALE.REVERSED` occurrence must be exercised on the same resolve path and its outcome recorded.

## 11. Review decision

```text
Result: CONDITIONAL_PASS
Reason: all M3 exit-criteria evidence is complete, including post-fix real PayPal
Sandbox acceptance (first payment, replay dedupe, suspend/activate ordering,
refund by sale_id, cancel/paid-through, browser navigation). Open items are
tracked product decisions (RECOVERY-01/PAY-02), not implementation defects;
PAYMENT.SALE.REVERSED live trigger is a sandbox limitation with the identical
handler path already accepted via REFUNDED.
Open P0: 0
Open P1: 0
Open P2: 1 (RECOVERY-01 tracked decision)
Next milestone may start: YES (M4 — Sketch Ready), subject to the §10 conditions
```
