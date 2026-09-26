# RV-01 / RV-02 — Critical / High remediation evidence

- Date: 2026-09-26
- Checkpoint: `main`, HEAD `81ca8cee8e60911997687c8f6518c9dea1dab79c`, uncommitted working tree.
- Result: **BLOCKED for milestone acceptance; implementation remediation ready for review**.
- Authority: AGENTS.md; TASK-BREAKDOWN RV-01/RV-02 and affected SP tasks; DEV-SPEC §9–10, §14–15, §20, §23; PAY-AUTH-01, TIME-01, ASSET-01, configurable PAY-02 policy.
- This is implementer verification, not an independent high-risk approval. Earlier handoffs/reviews describe historical checkpoints; they do not establish acceptance of this changed implementation.

## Confirmed issues and remediation

| Finding | Spec Requirement | Actual implementation after fix | Evidence | Recommended follow-up |
|---|---|---|---|---|
| Critical C1 — unverified email ownership | Server-derived binding; no cross-session disclosure (§20) | Unknown subscriptions require provider custom_id matching a stored session. Artifact reads remain session-scoped; email fallback removed. Email uniqueness is preserved. | subscription_service.py `reconcile_subscription`; status_service.py `get_artifact_statuses`; tests `test_missing_binding_sale_stays_pending_even_with_unique_payer_email`, same-email Result/status regressions | Independent ownership review; authenticated recovery remains outside scope. |
| High H1 — latest payment used as first | Persist first successful provider payment and derive +12h/+24h (§9.4, §10) | Reconciliation records valid completed transactions first, then chooses earliest successful ledger time. Summary-only last_payment cannot entitle. Delayed earlier evidence atomically corrects base/unlocks without replacing durable assets; renewals never move them forward. | subscription_service.py `_reconcile_subscription_payments`, `activate_from_payment`; regression tests earliest/concurrency/delayed-earlier | Review correction behavior against first-payment invariant; no new entitlement on renewal. |
| High H2 — unresolved events acknowledged | Retry/dedup must not lose effects (§9.5–9.6) | Verified receipt persists; business writes use savepoint; failure rolls back business, leaves processed_at null and sanitized error, returns retryable failure. Only completed events deduplicate. | webhook_service.py `process_webhook`; outage and injected-failure tests | Real provider retry exercise still required. |
| High H3 — refund identity/order | Durable ledger linked to actual provider payment (§9.7, §14) | Refund uses sale_id, reversal can use sale resource id; parent_payment never identifies sale. Missing sale remains retryable. Duplicate sale cannot undo refund. | webhook_service.py refund handler; ledger_service.py; parameterized refund/reversal test | Real refund/reversal payload replay still required. |
| High H4 — stale status/billing regression | Out-of-order events cannot regress paid/cancelled state (§9.5–9.8) | Persisted status/billing checkpoints reject stale events; terminal state protected; activation alone cannot clear failure; older sale cannot clear newer failure. | payment_consistency.py; 0004 migration; stale-state and billing regression tests | Historical timestamps not present in DB cannot be reconstructed by migration. |
| High H5 — plan policy bypass | Server validates selected plan and configured eligibility (§9.3–9.4) | Confirm and unknown-subscription reconciliation reuse OfferService policy; configured blocked/standard/intro policy enforced before binding. | subscription_service.py `_validate_new_subscription_plan`; parameterized both-path tests | PAY-02 stays open; no policy selected by this fix. |
| High R1 — full transaction concurrency evidence missing | DB uniqueness + idempotent financial/entitlement writes (§14) | PostgreSQL transaction advisory locks serialize event, subscription, session and ledger writes, including absent rows. | 6 simultaneous same-event calls, 6 distinct events/same sale, webhook vs reconciliation tests | Real PayPal concurrency acceptance remains NOT_RUN. |

Paths above are under `backend/app/soulmate/services/`, `backend/alembic/versions/`, and `backend/tests/test_payment_security_regressions.py`; additional ownership regressions are in test_artifact_status.py, test_result_api.py and test_subscription_reconciliation.py.

## Reproducible automated evidence

- `.venv/bin/python backend/scripts/test_isolated.py backend/tests -q --tb=short`: **504 passed, 4 warnings**, 20.48 seconds. Warnings are existing httpx per-request cookie deprecations.
- Disposable real PostgreSQL: empty schema → 0003 → populated representative legacy rows → 0004 → 0003 → 0004; schema, timestamp backfill and preserved business data assertions **PASS**. Test database removed on completion.
- Provider and verification responses in these tests are mocked. Test runner supplies fake provider credentials. These are not live Sandbox payment tests.
- `npm --prefix frontend test -- --run`: **290 passed**, 24 files.
- `npm --prefix frontend run typecheck -- --incremental false`: **PASS**.
- `npm --prefix frontend run lint`: **PASS**.
- `npm --prefix frontend run build`: **PASS**, production routes compiled and prerendered.
- `git diff --check`: **PASS**.

## Deployment / rollback / residual evidence

- Additive migration `0004_payment_event_order`; published older migrations unchanged. Apply migration before deploying new model/service code. Shared development database was not upgraded by this remediation.
- Downgrade removes ordering checkpoints, not payments/artifacts; it also removes new stale-event protection. Roll back application code together with schema.
- Existing wrongly bound records are not reassigned/deleted automatically. Historical binding and wrong-first-time records require scoped operational investigation; reconciliation can correct earlier payment evidence for trusted bindings.
- Missing binding/unmatched refund stays pending for provider retry or an authorized replay after prerequisites exist; no background replay scheduler added.
- Same-email second anonymous session remains unable to recover a first session’s Sketch until a verified identity/recovery flow exists. This preserves confidentiality and uniqueness.
- Medium session `paid` versus `SUBSCRIBED` enum inconsistency remains outside this repair batch.
- Post-fix real PayPal Sandbox first payment/refund/reversal/retry/browser acceptance: **NOT_RUN**. Historical provider evidence from the review is not post-fix evidence.
- Independent RV-01/RV-02 re-review and M2/M3 gate review: **NOT_RUN**. No milestone PASS, no next phase, no commit/push.

## Source evidence index (working-tree line numbers)

- C1: `backend/app/soulmate/services/subscription_service.py:420`, `backend/app/soulmate/services/status_service.py:28`; regression `backend/tests/test_payment_security_regressions.py:151`.
- H1: `backend/app/soulmate/services/subscription_service.py:335`, `backend/app/soulmate/services/subscription_service.py:375`; regressions `backend/tests/test_payment_security_regressions.py:103`, `backend/tests/test_payment_security_regressions.py:273`.
- H2: `backend/app/soulmate/services/webhook_service.py:150`; regressions `backend/tests/test_payment_security_regressions.py:129`, `backend/tests/test_payment_security_regressions.py:291`.
- H3: `backend/app/soulmate/services/webhook_service.py:434`, `backend/app/soulmate/services/ledger_service.py:36`; regression `backend/tests/test_payment_security_regressions.py:170`.
- H4: `backend/app/soulmate/services/payment_consistency.py:24`, `backend/alembic/versions/0004_payment_event_order.py:1`; regressions `backend/tests/test_payment_security_regressions.py:194`, `backend/tests/test_payment_security_regressions.py:208`.
- H5: `backend/app/soulmate/services/subscription_service.py:302`; regression `backend/tests/test_payment_security_regressions.py:229`.
- R1: `backend/app/soulmate/services/payment_consistency.py:16`; regressions `backend/tests/test_payment_security_regressions.py:250`, `backend/tests/test_payment_security_regressions.py:259`.
- Isolated PostgreSQL/migration runner: `backend/scripts/test_isolated.py:1`.

## Addendum (2026-09-26, follow-up batch)

- **M7 closed:** the post-payment session status writer now emits the canonical `SessionStatus.SUBSCRIBED` (`subscription_service.activate_from_payment`); additive migration `0005_legacy_session_status` normalizes legacy rows (`'paid'` → `'SUBSCRIBED'`) and the isolated runner asserts the normalization across upgrade/downgrade/re-upgrade. Tests updated to the canonical value (backend 504/504 in the isolated runner).
- **M8 closed:** `PROJECT-STATE.md` records M2 as BLOCKED; `TASK-BREAKDOWN.md` RV-01/RV-02 and affected SP tasks are REVIEW; `docs/reviews/M2-PAYPAL-SANDBOX-REVIEW.md` gained a supersession addendum (historical PASS superseded; SP-502 mislabel corrected).
- **Landed as commits** on `main` (this remediation batch plus the follow-ups above were committed after the original "no commit/push" checkpoint; see `git log` from `9f53818` onward).
- Unchanged residuals: post-fix real PayPal Sandbox payment/refund/reversal/retry/browser acceptance and the independent RV-01/RV-02 re-review + M2/M3 gate decisions remain NOT_RUN for the independent reviewer.
