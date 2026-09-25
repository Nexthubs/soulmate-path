# SP-406 — Webhook Event Idempotency and Out-of-Order Handling High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-25
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-406`
- **Context refs used:** DEV-SPEC §9.5–9.6, §14 | Decisions: `PAY-AUTH-01`, `TIME-01` | Dependency handoffs: `SP-405`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-406` (Event idempotency and out-of-order handling)

Handoffs:
- `docs/handoffs/SP-406.md`
- `docs/handoffs/SP-405.md`

## 2. High-risk invariants evaluated
1. **Entitlement Authority (`PAY-AUTH-01`):**
   - Entitlement begins on first successful payment (`subscription_success_at` populated, artifact rows created).
   - Replay of payment webhook events must NOT create duplicate entitlement timestamps or reset countdown timers (`TIME-01`).
2. **Terminal State Monotonicity & Out-of-Order Protection:**
   - Once marked `CANCELLED` or `EXPIRED`, subscriptions must never regress to `ACTIVE` or `PROCESSING` due to delayed or rogue `BILLING.SUBSCRIPTION.ACTIVATED` webhooks.
   - Events with older timestamps than recorded state transitions (`cancelled_at`, `suspended_at`) must be discarded.
3. **Ledger Integrity & In-Flight Payments:**
   - Payments completing after cancellation must be recorded in `subscription_payments` for financial auditability without reactivating the subscription.
   - Payment failures on renewal cycles must record failed payment records without revoking already-purchased entitlements or deleting generated assets.
4. **Database Uniqueness & Concurrency Safety:**
   - Provider event ID (`uq_paypal_webhook_events_event_id`) and provider payment ID (`uq_subscription_payments_provider_payment_id`) must prevent duplicate inserts.
   - Sketch artifact creation must honor `uq_soulmate_one_sketch_per_email`.

## 3. Implementation review & evidence

### 3.1 Webhook Replay & Ledger Idempotency
- **Inspection:** Inspected `backend/app/soulmate/services/webhook_service.py` (`process_webhook`, `_handle_payment_sale_completed`).
- **Finding:**
  - `process_webhook` checks `paypal_webhook_events` for existing `event_id` before processing. Replays return immediately with `status="DUPLICATE"` and without mutating downstream tables.
  - `_handle_payment_sale_completed` checks `SubscriptionPayment.provider_payment_id` prior to insertion, ensuring that even if PayPal issues a new event ID for an already-settled capture, no duplicate payment ledger row is inserted.
- **Automated Evidence:**
  - `test_replay_payment_event_n_times_single_ledger_and_activation`: 5 consecutive webhook post requests result in exactly 1 `SubscriptionPayment` row and 1 sketch/report artifact pair.
  - `test_replayed_payment_id_across_different_event_ids_is_idempotent`: Identical `provider_payment_id` under 2 distinct webhook event IDs produces 2 event audit records but strictly 1 payment ledger entry.

### 3.2 Out-of-Order Delivery & Terminal State Guards
- **Inspection:** Inspected `_handle_subscription_activated`, `_handle_subscription_cancelled`, and `_handle_subscription_suspended`.
- **Finding:**
  - `_handle_subscription_activated` checks `sub.provider_status in ("CANCELLED", "EXPIRED")` and rejects state mutation.
  - `_handle_subscription_activated` verifies `event_time > sub.cancelled_at` and `event_time > sub.suspended_at`.
  - In-flight payments arriving after cancellation update `first_payment_at` and ledger only, explicitly checking `if sub.provider_status not in ("CANCELLED", "EXPIRED")` before setting `sub.provider_status = "ACTIVE"`.
- **Automated Evidence:**
  - `test_stale_activated_event_does_not_regress_cancelled_subscription`: Stale `ACTIVATED` event cannot overwrite `CANCELLED` status.
  - `test_terminal_cancelled_state_cannot_be_activated_even_by_newer_event`: Even an `ACTIVATED` event with a future timestamp cannot reopen a `CANCELLED` subscription.
  - `test_stale_activated_event_does_not_regress_suspended_subscription`: Stale `ACTIVATED` event cannot clear `SUSPENDED` status.
  - `test_newer_activated_event_resumes_suspended_subscription`: Legitimate future `ACTIVATED` event reactivates a `SUSPENDED` subscription.
  - `test_payment_completed_after_cancellation_records_ledger_without_reactivating`: Completed payment records to ledger while subscription remains `CANCELLED`.

### 3.3 Entitlement Preservation on Failure/Cancellation
- **Inspection:** Inspected `_handle_payment_failed` and `_handle_subscription_cancelled`.
- **Finding:**
  - `_handle_subscription_cancelled` marks `provider_status = "CANCELLED"`, updates `cancelled_at`, but never nullifies `SoulmateSession.subscription_success_at` or deletes rows from `soulmate_artifacts`.
  - `_handle_payment_failed` creates a `FAILED` ledger record. If `first_payment_at` was previously recorded, `subscription_success_at` is preserved.
- **Automated Evidence:**
  - `test_subsequent_payment_failed_does_not_clear_first_entitlement`: Emitted `BILLING.SUBSCRIPTION.PAYMENT.FAILED` preserves existing `subscription_success_at` and artifact records.

### 3.4 Ambiguous State Reconciliation
- **Inspection:** Inspected `reconcile_subscription` in `webhook_service.py`.
- **Finding:**
  - Queries PayPal REST API `/v1/billing/subscriptions/{id}` using authenticated `PayPalClient`.
  - Matches session using `custom_id` or subscriber email.
  - Injects new subscription record if missing locally, but respects monotonicity: if the local database already marks the subscription as `CANCELLED`, PayPal API response cannot regress it to `ACTIVE`.
- **Automated Evidence:**
  - `test_reconcile_subscription_creates_missing_subscription_linked_to_session`: Missing subscription is populated and linked to session.
  - `test_reconciliation_preserves_local_terminal_cancelled_state`: Locally `CANCELLED` subscription is preserved during reconciliation.

## 4. Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Webhook Idempotency & Ordering Test Suite | PASS | 10/10 passed in `backend/tests/test_webhook_idempotency_ordering.py` |
| Full backend regression | PASS | 398/398 passed in 22.57s |
| Frontend Vitest regression | PASS | 252/252 passed in 1.15s |
| Frontend typecheck & lint | PASS | 0 errors |

## 5. Review Conclusion
**PASS** — SP-406 satisfies all high-risk requirements for event idempotency, out-of-order tolerance, and terminal state protection. It strictly safeguards `PAY-AUTH-01` and `TIME-01`.
Safe to proceed to `SP-407` (Payment ledger).
