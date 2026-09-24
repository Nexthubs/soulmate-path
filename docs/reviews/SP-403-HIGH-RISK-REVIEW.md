# SP-403 — Confirm Subscription API High-Risk Review

- **Review result:** CONDITIONAL_PASS (Conditional on Milestone M2 end-to-end live PayPal Sandbox gate; all automated verification PASS)
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-24
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-403`
- **Context refs used:** DEV-SPEC §9.3–9.4, §15.7–15.8 | Decisions: `PAY-AUTH-01` | Dependency handoffs: `SP-402`, `SP-401`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-403` (Confirm subscription API & backend status check)

Handoffs:
- `docs/handoffs/SP-403.md`
- `docs/handoffs/SP-402.md`
- `docs/handoffs/SP-401.md`

## 2. Exit criteria & high-risk invariants
1. **Server Validation of Provider Subscription ID:**
   - Server must verify the subscription ID exists on PayPal via REST API `GET /v1/billing/subscriptions/{id}`.
   - Server must reject rogue plans not configured in project settings.
   - Server must reject terminal invalid states (`CANCELLED`, `EXPIRED`, `SUSPENDED`).
2. **Ownership Binding & Anti-Hijacking (IDOR Prevention):**
   - Subscription must be strictly bound to the authenticated user's session.
   - A subscription ID already registered to one session MUST NOT be claimed or confirmed by another session.
3. **Idempotency:**
   - Duplicate confirmation requests for the same session and subscription must be idempotent and return HTTP 200 without creating duplicate database rows or throwing database errors.
4. **Entitlement Authority (`PAY-AUTH-01`):**
   - Confirming a subscription MUST NOT set `first_payment_at` or mark `is_paid = True`.
   - Entitlement remains pending (`status = "PROCESSING"`) until verified payment webhook reconciliation (`PAYMENT.SALE.COMPLETED`).

## 3. Implementation review & evidence

### 3.1 Entitlement Authority (`PAY-AUTH-01`)
- **Inspection:** Inspected `SubscriptionService.confirm_paypal_subscription` in `backend/app/soulmate/services/subscription_service.py`.
- **Finding:**
  - `new_subscription` is persisted with `first_payment_at=None`.
  - Returned response has `status="PROCESSING"` and `is_paid=False`.
  - `get_subscription_status` returns `is_paid=False` until `sub.first_payment_at` is populated.
- **Automated Evidence:** Verified by `test_confirm_subscription_success_and_pay_auth_01` in `backend/tests/test_subscription_confirm.py`.

### 3.2 Ownership & Cross-Session Anti-Hijacking
- **Inspection:** Inspected database lookup and session verification in `SubscriptionService`.
- **Finding:**
  - If `existing_sub` exists and `existing_sub.session_id != session.id`: raises `ForbiddenOwnershipError`.
  - Endpoint enforces `verify_session_ownership` if explicit `session_id` is supplied in the request.
- **Automated Evidence:** Verified by `test_confirm_subscription_cross_session_hijack_prevention` and `test_api_confirm_subscription_idor_rejected`.

### 3.3 Idempotency
- **Inspection:** If `existing_sub` exists for the current session, the service returns the existing record immediately with an idempotent message.
- **Finding:**
  - No secondary INSERT is attempted.
  - Zero constraint violation errors.
- **Automated Evidence:** Verified by `test_confirm_subscription_idempotency_duplicate`.

### 3.4 Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Pytest SP-403 suite | PASS | 10/10 tests pass |
| Pytest backend full regression | PASS | 341/341 tests pass |
| Vitest frontend tests | PASS | 252/252 tests pass |
| TypeScript check | PASS | Zero type errors (`tsc --noEmit`) |
| ESLint check | PASS | Zero linter warnings/errors |
| Live Sandbox transaction | NOT_RUN | Ready for live verification upon credential injection |

## 4. Review conclusion
The SP-403 implementation satisfies all P0 acceptance criteria and strictly upholds invariant `PAY-AUTH-01`.
Approved with status **CONDITIONAL_PASS** pending live PayPal Sandbox end-to-end execution in Milestone M2 review.
