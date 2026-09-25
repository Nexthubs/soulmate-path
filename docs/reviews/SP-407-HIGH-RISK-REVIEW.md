# SP-407 — Payment Ledger High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-25
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-407`
- **Context refs used:** DEV-SPEC §9.4–9.7, §14 | Decisions: `PAY-AUTH-01` | Dependency handoffs: `SP-406`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-407` (Payment ledger)

Handoffs:
- `docs/handoffs/SP-407.md`
- `docs/handoffs/SP-406.md`

## 2. High-risk invariants evaluated
1. **Durable Ledger Integrity (DEV-SPEC §9.4–9.7, §14):**
   - Every completed provider payment must have durable provider payment ID, amount, currency, paid time, subscription link, and billing cycle context.
   - Raw JSON payloads must be preserved for dispute resolution and financial auditability.
2. **Provider Payment ID Uniqueness & Idempotency:**
   - Provider payment IDs must be strictly unique (`UNIQUE` constraint on `provider_payment_id`).
   - Duplicate payment events (e.g. PayPal retries, delayed webhooks, multiple capture attempts) must not create multiple rows in `subscription_payments`.
3. **Reconciliation & Support Authority (DEV-SPEC §20):**
   - Lookup by provider payment ID, subscription ID, or customer email must be fast, accurate, and contextually rich (hydrating subscription, session, and email).
   - User-facing session billing endpoints must be strictly protected against Insecure Direct Object References (IDOR).
4. **Entitlement Authority Separation (`PAY-AUTH-01`):**
   - Failed renewal payments must record `FAILED` status in the ledger without wiping previously granted entitlements (`subscription_success_at` and generated artifacts remain preserved).
   - Refunds and reversals must be explicitly recorded without mutating past generation deadlines.

## 3. Implementation review & evidence

### 3.1 Durable Payment Fields & Cycle Context
- **Inspection:** Inspected `backend/app/soulmate/services/ledger_service.py` (`record_payment`).
- **Finding:**
  - `record_payment` enforces non-empty `provider_payment_id`.
  - Amount is validated as non-negative Decimal; currency is stored as ISO 4217 uppercase string.
  - Cycle number is automatically derived from the count of existing payments for the subscription (`cycle_no = count + 1`), ensuring intro month is cycle 1 and renewals increment monotonically.
  - Complete provider payload is stored in `raw_json`.
- **Automated Evidence:**
  - `test_record_completed_payment_persists_all_durable_fields`: all fields verified matching input.
  - `test_subsequent_cycle_payments_derive_monotonic_cycle_numbers`: cycles 1, 2, 3 properly derived.

### 3.2 Duplicate Prevention & Concurrency Safety
- **Inspection:** Inspected `record_payment` idempotency check and database schema.
- **Finding:**
  - Service queries `SubscriptionPayment` by `provider_payment_id` before insertion.
  - If existing, returns `(existing_payment, False)`.
  - Database constraint `subscription_payments_provider_payment_id_key` acts as secondary defense-in-depth against race conditions.
- **Automated Evidence:**
  - `test_duplicate_provider_payment_id_cannot_create_multiple_rows`: 5 repeat calls return the identical record ID, with database row count remaining exactly 1.

### 3.3 Customer Support & Reconciliation Lookups
- **Inspection:** Inspected `PaymentLedgerService` query methods and `backend/app/api/soulmate/ledger.py`.
- **Finding:**
  - `get_payment_by_provider_payment_id` joins `SubscriptionPayment` with `Subscription` and `SoulmateSession` to hydrate `provider_subscription_id`, `session_public_id`, and `customer_email`.
  - `get_payments_by_email` uses normalized email for accurate cross-session customer dispute lookups.
  - `search_payments` provides multi-field filtering (provider payment ID, subscription ID, email, status, date range) with total count and pagination.
  - `get_subscription_ledger_summary` calculates completed, failed, and refunded totals and net amount paid.
- **Automated Evidence:**
  - `test_lookup_payment_by_provider_payment_id_hydrates_context`: PASS.
  - `test_lookup_payments_by_email`: PASS.
  - `test_record_refund_and_summary_aggregation`: PASS.
  - `test_search_payments_with_filters_and_pagination`: PASS.
  - `test_api_support_lookup_by_provider_payment_id`: PASS.
  - `test_api_support_ledger_search_endpoint`: PASS.

### 3.4 IDOR Protection on User Session Endpoints
- **Inspection:** Inspected `GET /api/soulmate/subscription/payments` in `backend/app/api/soulmate/subscription.py`.
- **Finding:**
  - Requires valid signed session cookie token via `extract_session_token` / `verify_session_token`.
  - Enforces `verify_session_ownership(requested_public_id, authenticated_public_id)`.
  - Rejects attempts to access another user's payment records with HTTP 403.
- **Automated Evidence:**
  - `test_api_session_payments_endpoint_idor_protected`: Authenticated session returns 200 with payment record; cross-session IDOR attempt returns 403 Forbidden.

## 4. Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Dedicated Payment Ledger Test Suite | PASS | 10/10 passed in `backend/tests/test_payment_ledger.py` |
| Webhook idempotency & ordering suite | PASS | 25/25 passed in `backend/tests/test_webhook_idempotency_ordering.py` + `backend/tests/test_paypal_webhooks.py` |
| Full backend regression | PASS | 408/408 passed in 26.82s |
| Frontend Vitest regression | PASS | 252/252 passed in 1.39s |
| Frontend typecheck & lint | PASS | 0 errors |

## 5. Review Conclusion
**PASS** — SP-407 satisfies all acceptance criteria. The payment ledger persists durable transaction records with cycle context, prevents duplicate rows via database constraints and application deduplication, provides rich customer support reconciliation capabilities, and protects user data against IDOR.
Safe to proceed to `SP-408` (Subscription reconciliation/state mapping).
