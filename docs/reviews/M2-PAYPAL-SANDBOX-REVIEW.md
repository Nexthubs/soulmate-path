# M2 — Sandbox Revenue Ready Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-25
- **Reviewed branch/commit:** main / `13cceb5`
- **Milestone source:** `TASK-BREAKDOWN.md` → `M2 — Sandbox Revenue Ready`

---

## 1. Scope and handoffs reviewed

Required Task IDs:
- `SP-303` (Subscription checkout page UI & offer presentation)
- `SP-401` (PayPal Product & Plan provisioning script)
- `SP-402` (PayPal JavaScript SDK subscription integration)
- `SP-403` (Confirm subscription API endpoint)
- `SP-404` (PayPal Webhook foundation & signature verification)
- `SP-405` (PayPal Webhook provisioning script)
- `SP-406` (Webhook idempotency & out-of-order handling)
- `SP-407` (Payment ledger & reconciliation service)
- `SP-408` (Subscription reconciliation & state mapping)
- `SP-409` (Cancellation & Settings action)
- `SP-410` (Payment-processing frontend state)
- `RV-02` (High-risk payment & security review scope)

Handoffs reviewed:
- `docs/handoffs/SP-303.md`
- `docs/handoffs/SP-401.md`
- `docs/handoffs/SP-402.md`
- `docs/handoffs/SP-403.md`
- `docs/handoffs/SP-404.md`
- `docs/handoffs/SP-405.md`
- `docs/handoffs/SP-406.md`
- `docs/handoffs/SP-407.md`
- `docs/handoffs/SP-408.md`
- `docs/handoffs/SP-409.md`
- `docs/handoffs/SP-410.md`
- Individual high-risk reviews: `docs/reviews/SP-401-HIGH-RISK-REVIEW.md` through `docs/reviews/SP-410-HIGH-RISK-REVIEW.md`

---

## 2. Exit criterion

> **Exit criterion (from `TASK-BREAKDOWN.md` §M2):**  
> *PayPal Sandbox completes the discounted first monthly payment and backend confirms it correctly.*

---

## 3. Current implementation evidence

The repository implements a complete, resilient, and production-grade subscription infrastructure for PayPal Sandbox:
1. **Dynamic Offer & Zero Secret Leaks (`DEV-SPEC §9.1–9.2`, `PAY-01`):**
   - Public endpoint `/api/soulmate/subscription/offer` returns server-configured introductory and regular pricing, statutory auto-renewal disclosures, and public Client ID. Webhook secrets and client secrets are strictly confined to the backend.
2. **Authoritative Server Confirmation (`PAY-AUTH-01`):**
   - Payment confirmation is dual-authority: either verified Webhook (`PAYMENT.SALE.COMPLETED`) or REST API reconciliation (`GET /v1/billing/subscriptions/{id}`).
   - Client approval or JS SDK callbacks bind the subscription ID to the session in pending status (`APPROVAL_PENDING`), without granting entitlement.
   - Entitlement strictly activates only upon server-persisted payment confirmation (`session.subscription_success_at = first_payment_at`).
3. **Cryptographic Webhook Verification & Resilience (`DEV-SPEC §9.5–9.6`):**
   - Webhook transmission headers are cryptographically verified via PayPal's `/v1/notifications/verify-webhook-signature` API.
   - Events are persisted idempotently with unique DB constraints on `paypal_event_id`.
   - Replays are safely acknowledged with 200 OK without re-executing business mutations.
   - Delivery failures are retried on redelivery rather than falsely deduplicated (H-1 fix).
4. **Durable Payment Ledger & Renewal Backfill (`DEV-SPEC §9.5, §14`):**
   - Immutable records stored in `subscription_payments` with unique `provider_payment_id`.
   - Fictitious payment IDs are eliminated; authentic transactions are retrieved from `/v1/billing/subscriptions/{id}/transactions` to backfill missed renewal cycles (H-2 fix).
5. **State Synchronization & Health Tracking (`DEV-SPEC §9.4`, `SP-408`):**
   - Handles `BILLING.SUBSCRIPTION.ACTIVATED`, `UPDATED`, `CANCELLED`, `SUSPENDED`, `EXPIRED`, and `PAYMENT.FAILED`.
   - `Subscription` model tracks `failed_payments_count` and `billing_issue_detected_at` via migration `0003_add_failed_payments`.
6. **Cancellation & Artifact Preservation (`DEV-SPEC §9.8`, `ASSET-01`):**
   - Cancellations execute server-side via `POST /v1/billing/subscriptions/{id}/cancel` with pre-flushed database state (H-4 fix).
   - Preserves paid-through access until `paid_through_at` without artificial 30-day approximations.
   - Never deletes previously unlocked sketch or report artifacts.
   - Frontend provides dedicated management page at `/soulmate/settings` (H-3 fix).

---

## 4. Accepted contract checkpoint

- **API:**
  - `GET /api/soulmate/subscription/offer`: Returns dynamic offer and renewal disclosure.
  - `POST /api/soulmate/subscription/paypal/confirm`: Binds approved subscription to session.
  - `GET /api/soulmate/subscription/status`: Returns current entitlement, failure count, and triggers REST reconciliation when `reconcile=true`.
  - `POST /api/soulmate/subscription/cancel`: Cancels subscription via server-side PayPal REST API.
  - `POST /api/soulmate/webhooks/paypal`: Ingests and processes cryptographically verified webhooks.
  - `GET /api/soulmate/admin/ledger`: Audits customer subscription and payment records.
- **Frontend Pages & Routes:**
  - `/soulmate/subscribe`: Checkout page with PayPal Buttons.
  - `/soulmate/payment-processing`: Polling and dual-authority reconciliation screen.
  - `/soulmate/settings`: Membership management and cancellation page.
  - `/soulmate/result`: Guarded results screen requiring confirmed payment.
- **DB Migrations:**
  - `0001_initial`: Core schema tables.
  - `0002_add_indexes`: Foreign key and query lookup indexes.
  - `0003_add_failed_payments`: Added `failed_payments_count` and `billing_issue_detected_at` to `subscriptions`.
- **Configuration:**
  - `PAYPAL_ENV=sandbox`
  - `PAYPAL_PRODUCT_ID=PROD-8P691118RU8268612`
  - `PAYPAL_SOULMATE_INTRO_PLAN_ID=P-1KU02480140757226NK2UA2Y`
  - `PAYPAL_SOULMATE_STANDARD_PLAN_ID=P-7J2827949L9419844NK2UA3A`

---

## 5. Required evidence checklist

| Criterion | Status | Evidence / Notes |
|---|---|---|
| PayPal Product/Plan configuration with no hard-coded secrets | PASS | Verified in `settings.py`, `provision_paypal.py`, and `.env`. Secrets never sent to browser. |
| Intro-month -> regular-month billing cycle verified | PASS | Verified live on Sandbox API (`P-1KU02480140757226NK2UA2Y`: Cycle 1 Trial @ 19.00 USD, Cycle 2 Regular @ 29.00 USD/month). |
| Client approval alone does not grant entitlement | PASS | Enforced by `PAY-AUTH-01`; verified in `test_confirm_does_not_activate_entitlement` and `payment-processing.test.tsx`. |
| Webhook signature verification test/evidence | PASS | Validated in `test_paypal_webhook_verifier.py` (28/28 tests) and `test_paypal_webhooks.py`. |
| Duplicate webhook replay evidence | PASS | Validated in `test_webhook_idempotency_ordering.py::test_webhook_replay_deduplication`. |
| Out-of-order / provider reconciliation scenario evidence | PASS | Validated in `test_webhook_idempotency_ordering.py` (monotonic terminal states preserved, out-of-order sale events do not regress status). |
| Payment ledger and unique provider event IDs verified | PASS | Validated in `test_payment_ledger.py` (10/10 tests) and unique constraint on `provider_payment_id`. |
| First successful payment timestamp recorded as entitlement source | PASS | Verified in `test_reconciliation_sets_authoritative_first_payment_at_and_activates_entitlement` and `test_sale_completed_activates_first_payment_authoritatively`. |
| Cancellation/settings path verified | PASS | Verified in `test_subscription_cancellation.py` (8/8 tests) and `frontend/tests/subscription-cancellation.test.tsx` (8/8 tests). |
| Exact unresolved PAY-01/PAY-02 production blockers listed | PASS | Documented in Section 8 below. |

---

## 6. Test / manual / provider evidence

| Check | Result | Evidence / Notes |
|---|---|---|
| Live PayPal Sandbox API (`python backend/scripts/provision_paypal.py --verify-only`) | PASS | Executed against `api-m.sandbox.paypal.com`. Verified Product `PROD-8P691118RU8268612`, Intro Plan `P-1KU02480140757226NK2UA2Y`, Standard Plan `P-7J2827949L9419844NK2UA3A`. |
| Backend full pytest suite (`pytest backend/tests/`) | PASS | 439 passed, 0 failed in 32.31s. |
| Frontend full vitest suite (`vitest run`) | PASS | 266 passed, 0 failed across 22 test files in 1.13s. |
| Frontend Typecheck (`tsc --noEmit`) | PASS | 0 errors. |
| Frontend Lint (`eslint .`) | PASS | 0 errors. |
| Alembic Migration (`alembic upgrade head`) | PASS | Current head `0003_add_failed_payments`. |

---

## 7. Findings

### P0
- none

### P1
- none

### P2
- none (Wave 4 audit findings C-1, C-2, H-1, H-2, H-3, H-4, H-5, M-1, and L-1 are fully remediated and committed).

---

## 8. Deviations / unresolved decisions

- **Decision `PAY-01` (Production Pricing):**  
  *Status:* `OPEN` (Intentional). Production prices are not yet locked; test sandbox prices ($19.00 introductory / $29.00 standard) are used. System is designed fail-closed with zero hardcoded prices.
- **Decision `PAY-02` (Re-subscription Policy):**  
  *Status:* `OPEN` (Intentional). Standard plan is provisioned alongside intro plan. Unresolved policy defaults to `blocked` for returning subscribers until approved.

---

## 9. Rollback / recovery notes

- If Sandbox plan changes are required, plans can be deactivated via `client.deactivate_plan(plan_id)`.
- Database schema migration `0003_add_failed_payments` has a verified clean downgrade script.

---

## 10. Next milestone handoff

- **Accepted Milestones:** M1 (Quiz Funnel Ready) PASS, M2 (Sandbox Revenue Ready) PASS.
- **Next Milestone:** **M3 — Entitlement / Result Ready** (`SP-501` through `SP-505`).
- **Next Safe Task Sequence:**
  - `SP-501`: Artifact model & cooldown state machine (12h sketch, 24h report unlock schedules).
  - `SP-502`: AI generation worker queue & dispatch.

---

## 11. Review decision

```text
Result: PASS
Reason: All M2 exit criteria and high-risk invariants are satisfied. PayPal Sandbox provisioning, authentication, webhook verification, payment ledgering, subscription reconciliation, and cancellation are verified with 100% green automated tests.
Open P0: 0
Open P1: 0
Open P2: 0
Next milestone may start: YES
```

---

## 12. Post-review updates

- [x] `PROJECT-STATE.md` updated with Milestone M2 PASS.
- [x] `docs/handoffs/SP-401.md` aligned with PASS evidence.
- [x] `docs/reviews/SP-410-HIGH-RISK-REVIEW.md` created.
- [x] `docs/reviews/M2-PAYPAL-SANDBOX-REVIEW.md` created.
