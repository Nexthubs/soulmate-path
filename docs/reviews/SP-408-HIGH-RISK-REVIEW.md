# SP-408 — Subscription Reconciliation and State Mapping High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-25
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-408`
- **Context refs used:** DEV-SPEC §9.4–9.8, §10 | Decisions: `PAY-AUTH-01`, `TIME-01` | Dependency handoffs: `SP-403`, `SP-406`, `SP-407`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-408` (Subscription reconciliation/state mapping)

Handoffs:
- `docs/handoffs/SP-408.md`
- `docs/handoffs/SP-407.md`
- `docs/handoffs/SP-406.md`
- `docs/handoffs/SP-403.md`

## 2. High-risk invariants evaluated
1. **Entitlement Authority via Dual Authority Paths (`PAY-AUTH-01`):**
   - Application state must not trust only a single webhook event.
   - When webhooks fail, are delayed, or out of order, querying PayPal's REST API (`GET /v1/billing/subscriptions/{id}`) must serve as authoritative reconciliation proof.
   - Entitlement begins on first successful payment (`billing_info.last_payment.time`); button clicks, approval popups, or pending states must never unlock content prematurely.
2. **First Payment Immutability (`TIME-01`):**
   - Once `first_payment_at` is set, subsequent renewal payments, replayed webhooks, or repeated reconciliations must NEVER mutate this timestamp or recalculate artifact unlock times (+12h sketch, +24h report).
3. **Monotonicity & Terminal State Protection:**
   - Subscriptions in local terminal states (`CANCELLED`, `EXPIRED`) must NEVER regress to `ACTIVE` or `APPROVAL_PENDING` due to stale API responses.
4. **Artifact Preservation on Cancellation & Disconnection:**
   - When a subscription is cancelled or expired, all previously unlocked or in-progress artifacts in `soulmate_artifacts` must be 100% retained.
   - Paid users retain access to generated artifacts indefinitely.

## 3. Implementation review & evidence

### 3.1 Reconciliation & Authoritative Entitlement (`PAY-AUTH-01`)
- **Inspection:** Inspected `reconcile_subscription` in `backend/app/soulmate/services/subscription_service.py`.
- **Finding:**
  - Queries `GET /v1/billing/subscriptions/{id}` using authenticated `PayPalClient`.
  - Parses `billing_info.last_payment`.
  - When `sub.first_payment_at is None` and `last_payment.time` is present:
    - Sets `sub.first_payment_at = last_paid_at`.
    - Activates `session.subscription_success_at = last_paid_at`, `session.status = "paid"`, `session.current_step = "result"`.
    - Calls `_ensure_artifacts_initialized` to create SKETCH (+12h) and REPORT (+24h) placeholders.
    - Records ledger entry in `SubscriptionPayment` via `PaymentLedgerService`.
- **Automated Evidence:**
  - `test_reconciliation_sets_authoritative_first_payment_at_and_activates_entitlement`: PASS.
  - `test_api_reconcile_endpoint`: PASS.
  - `test_api_status_polling_with_reconcile_query`: PASS.

### 3.2 Immutability of First Payment (`TIME-01`)
- **Inspection:** Inspected conditional check on `sub.first_payment_at` during reconciliation.
- **Finding:**
  - If `sub.first_payment_at` is already populated, it is ignored during subsequent payment reconciliations; only `next_billing_at` and `paid_through_at` are updated.
- **Automated Evidence:**
  - `test_subsequent_reconciliation_preserves_first_payment_at_immutable`: Subsequent renewal timestamp does not overwrite initial entitlement timestamp.

### 3.3 Terminal State Monotonicity
- **Inspection:** Inspected monotonicity check in `reconcile_subscription`.
- **Finding:**
  - If `sub.provider_status in ("CANCELLED", "EXPIRED")` and `remote_status in ("ACTIVE", "APPROVAL_PENDING", "APPROVED")`:
    - The state change is explicitly rejected and logged.
- **Automated Evidence:**
  - `test_reconciliation_preserves_terminal_cancelled_and_expired_states`: PASS.

### 3.4 Artifact Preservation on Cancellation
- **Inspection:** Inspected cancellation mapping branch in `reconcile_subscription` and `get_subscription_status`.
- **Finding:**
  - No delete operations exist on `SoulmateArtifact`.
  - `Subscription.cancelled_at` is recorded and `paid_through_at` is maintained.
- **Automated Evidence:**
  - `test_cancellation_reconciliation_never_deletes_already_owned_artifacts`: Artifacts remain with identical IDs, `generation_status = "COMPLETED"`, and full storage keys after subscription cancellation.

## 4. Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Dedicated Reconciliation Test Suite | PASS | 8/8 passed in `backend/tests/test_subscription_reconciliation.py` |
| Full billing suite (confirm + webhooks + ledger + reconciliation) | PASS | 40/40 passed in 4.38s |
| Full backend regression | PASS | 416/416 passed in 25.94s |
| Frontend Vitest regression | PASS | 252/252 passed in 1.05s |
| Frontend typecheck & lint | PASS | 0 errors |

## 5. Review Conclusion
**PASS** — SP-408 fulfills all requirements for provider state reconciliation and predictable state mapping. It strictly maintains invariants `PAY-AUTH-01` and `TIME-01`, guarantees terminal state monotonicity, and preserves all paid artifacts.
Safe to proceed to `SP-409` (Cancellation and Settings action).
