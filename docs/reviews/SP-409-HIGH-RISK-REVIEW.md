# SP-409 — Cancellation and Settings action High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-25
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-409`
- **Context refs used:** DEV-SPEC §9.8, §15.9 | Decisions: `PAY-AUTH-01`, `TIME-01`, `ASSET-01` | Dependency handoffs: `SP-408`

---

## 1. Scope and handoffs reviewed

Required Task IDs:
- `SP-409` (Cancellation and Settings action)

Handoffs:
- `docs/handoffs/SP-409.md`
- `docs/handoffs/SP-408.md`

---

## 2. High-risk invariants evaluated

1. **Server-Side Provider API Authority (`DEV-SPEC §9.8`):**
   - Cancellation must be executed through the authoritative server-side PayPal REST API (`POST /v1/billing/subscriptions/{id}/cancel`).
   - Browser or client callbacks must never unilaterally mark a subscription cancelled without server execution.
2. **Paid-Through Access Preservation (`DEV-SPEC §9.8, §15.9`):**
   - Before invoking PayPal cancellation, the backend must save PayPal's latest `billing_info.next_billing_time` as local `paid_through_at`.
   - Access to paid features continues until `paid_through_at`, decoupling cancellation of future renewals from immediate access termination.
3. **Artifact Retention & Non-Destruction (`DEV-SPEC §9.8, ASSET-01`):**
   - Cancelling a subscription must NEVER delete, hide, or degrade completed or in-progress artifacts in `soulmate_artifacts`.
   - The user permanently owns their generated Soulmate Sketch and Report.
4. **Repeated Cancellation Idempotency:**
   - Repeated requests to cancel an already-cancelled subscription must return safe 200 responses with the cancelled state, avoiding repeat provider calls or user-facing errors.
   - Resilient handling of PayPal HTTP 422 `SUBSCRIPTION_STATUS_INVALID` when a subscription was already cancelled directly on PayPal.
5. **Authorization and IDOR Prevention:**
   - The cancel endpoint must verify session token authenticity and match `session_id` to prevent cross-account cancellation hijacking.

---

## 3. Implementation review & evidence

### 3.1 Server-side Provider Cancellation (`DEV-SPEC §9.8`)
- **Inspection:** Inspected `SubscriptionService.cancel_subscription` and `PayPalClient.cancel_subscription`.
- **Finding:**
  - Invokes `POST /v1/billing/subscriptions/{id}/cancel` with authenticated OAuth bearer token and user-facing cancellation reason.
  - Successfully parses 204 No Content responses from PayPal.
- **Automated Evidence:**
  - `backend/tests/test_subscription_cancellation.py::test_cancel_subscription_success_via_provider_api`: PASS.

### 3.2 Paid-Through Access & Renewal Clearing
- **Inspection:** Inspected pre-cancellation fetching of `next_billing_time`.
- **Finding:**
  - Fetches subscription details from PayPal prior to cancellation.
  - Saves `billing_info.next_billing_time` into `sub.paid_through_at`.
  - Clears `sub.next_billing_at = None` so no future billing renewals are expected or displayed.
  - Route guard checks and frontend components use `paid_through_at` to accurately reflect active status until the period expires.
- **Automated Evidence:**
  - `backend/tests/test_subscription_cancellation.py::test_cancel_subscription_success_via_provider_api`: PASS (`paid_through_at` populated and verified within 5s).
  - `frontend/tests/subscription-cancellation.test.tsx`: PASS (renders "Active through Oct 25, 2026").

### 3.3 Repeat / Idempotent Cancellation Safety
- **Inspection:** Inspected idempotency guard at the beginning of `cancel_subscription`.
- **Finding:**
  - If `sub.provider_status == "CANCELLED"` or `sub.cancelled_at` is set, returns `SubscriptionCancelResponse` immediately with cached timestamps and skips remote PayPal API calls.
  - PayPal HTTP 422 responses with `SUBSCRIPTION_STATUS_INVALID` are caught and treated as successful idempotent cancellation.
- **Automated Evidence:**
  - `backend/tests/test_subscription_cancellation.py::test_repeated_cancel_is_safe_and_idempotent`: PASS (only 1 call to PayPal API made across 2 consecutive cancel requests).

### 3.4 Artifact Retention Invariant (`ASSET-01`)
- **Inspection:** Verified database operations during cancellation.
- **Finding:**
  - No `delete` operations are executed against `soulmate_artifacts` or `subscription_payments`.
  - Completed sketches and reports remain queryable and accessible.
- **Automated Evidence:**
  - `backend/tests/test_subscription_cancellation.py::test_cancelled_users_retain_previously_generated_artifacts`: PASS (100% of artifact rows retained with original storage keys).
  - `backend/tests/test_subscription_cancellation.py::test_webhook_cancellation_sets_paid_through_and_retains_artifacts`: PASS.

### 3.5 Authorization & IDOR Defense
- **Inspection:** Inspected `cancel_subscription_endpoint` in `backend/app/api/soulmate/subscription.py`.
- **Finding:**
  - Calls `verify_session_ownership(requested_public_id=payload.session_id, authenticated_public_id=authenticated_id)`.
  - Rejects cross-session cancellation requests with HTTP 403 `FORBIDDEN_OWNERSHIP`.
- **Automated Evidence:**
  - `backend/tests/test_subscription_cancellation.py::test_cancel_idor_protection`: PASS (returns 403 `FORBIDDEN_OWNERSHIP`).

---

## 4. Test Summary

```text
pytest backend/tests/test_subscription_cancellation.py               PASS 7/7
pytest billing regression suite (9 test files)                       PASS 121/121
pytest backend full regression (23 files)                           PASS 423/423
vitest frontend cancellation suite                                   PASS 5/5
vitest frontend full regression (21 files)                          PASS 257/257
tsc --noEmit                                                         PASS 0 errors
eslint .                                                             PASS 0 errors
```

---

## 5. Review Conclusion

**PASS**.
All acceptance criteria and high-risk invariants for `SP-409` have been satisfied with reproducible automated test evidence.
