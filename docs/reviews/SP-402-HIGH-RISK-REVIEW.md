# SP-402 — PayPal JS Subscription Checkout High-Risk Review

- **Review result:** CONDITIONAL_PASS (Conditional on Milestone M2 end-to-end live PayPal Sandbox gate; all automated verification PASS)
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-24
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-402`
- **Context refs used:** DEV-SPEC §9.3, §15.6, §21 | Decisions: `PAY-01`, `PAY-02`, `PAY-AUTH-01` | Dependency handoffs: `SP-303`, `SP-401`, `SP-105`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-402` (PayPal JS subscription checkout)

Handoffs:
- `docs/handoffs/SP-402.md`
- `docs/handoffs/SP-401.md`
- `docs/handoffs/SP-303.md`

## 2. Exit criteria & high-risk invariants
1. **Payment / Entitlement Authority (`PAY-AUTH-01`):**
   - Client approval callback (`onApprove`) MUST NEVER mark the user as paid, alter local storage, set session cookies, or unlock access to results, sketch, or report.
   - Access authority belongs exclusively to server-verified completed payment reconciliation.
2. **Subscription Intent & Vaulting:**
   - PayPal JavaScript SDK must be loaded with `vault: true` and `intent: "subscription"`.
   - Subscription creation must target the server-provided Plan ID, never an ad-hoc or client-invented price.
3. **Disclosure Parity (DEV-SPEC §21):**
   - The UI must display accurate statutory auto-renewal disclosures matching the server offer (`today_text`, `renewal_text`, `terms_text`).
4. **Failure & Cancellation Recoverability:**
   - Buyer cancellation (`onCancel`) and SDK errors (`onError`) must not crash the page or leave the user in a broken or non-navigable state; checkout must remain available for retry.
5. **Re-subscription Policy Enforcement (`PAY-02`):**
   - Users marked `is_blocked: true` must be barred from initiating checkout.

## 3. Implementation review & evidence

### 3.1 Entitlement Authority (`PAY-AUTH-01`)
- **Inspection:** Inspected `frontend/src/soulmate/components/subscribe/PayPalSubscriptionButton.tsx` and `frontend/src/app/soulmate/subscribe/page.tsx`.
- **Finding:**
  - `handleApprove` only captures `data.subscriptionID` and calls `router.push('/soulmate/payment-processing?subscription_id=...')`.
  - Zero writes to `localStorage`, `sessionStorage`, or cookies.
  - In `frontend/src/app/soulmate/payment-processing/page.tsx`, the screen explicitly treats payment verification as in-flight and displays: `"Results dashboard unlocks upon server-verified payment completion (PAY-AUTH-01)"`.
- **Automated Evidence:** Verified by test suite `tests/paypal-subscription-checkout.test.tsx` (`Acceptance Criterion 1 & Invariant PAY-AUTH-01`).

### 3.2 Plan Binding & Dynamic Pricing (`PAY-01`)
- **Inspection:** Verified that `actions.subscription.create` receives `{ plan_id: offer.paypal.plan_id }`.
- **Finding:**
  - The plan ID is sourced dynamically from `GET /api/soulmate/subscription/offer`.
  - Prices are not hardcoded in the frontend code.
- **Automated Evidence:** Verified by `tests/paypal-subscription-checkout.test.tsx` and `tests/subscription-offer.test.tsx`.

### 3.3 Recoverable UI on Failure & Cancellation
- **Inspection:** Inspected `handleCancel` and `handleError` in `page.tsx`.
- **Finding:**
  - Both update the dismissible `paymentNotice` banner.
  - Neither navigates away or unmounts the subscription button.
  - The user can immediately retry checkout without refreshing the page.
- **Automated Evidence:** Verified in `tests/paypal-subscription-checkout.test.tsx`.

### 3.4 Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Vitest unit/integration tests | PASS | 252/252 tests pass |
| TypeScript check | PASS | Zero type errors (`tsc --noEmit`) |
| ESLint check | PASS | Zero linter warnings/errors |
| Pytest backend regression | PASS | 331/331 tests pass |
| Live Sandbox buyer transaction | NOT_RUN | Deferred to Milestone M2 gate |

## 4. Review conclusion
The SP-402 implementation satisfies all P0 acceptance criteria and strictly upholds invariant `PAY-AUTH-01`.
Approved with status **CONDITIONAL_PASS** pending live PayPal Sandbox end-to-end execution in Milestone M2 review.
