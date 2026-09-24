# SP-404 — PayPal Webhook Endpoint High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-24
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-404`
- **Context refs used:** DEV-SPEC §9.5–9.6 | Decisions: `PAY-AUTH-01` | Dependency handoffs: `SP-002`, `SP-004`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-404` (PayPal webhook endpoint with raw body)

Handoffs:
- `docs/handoffs/SP-404.md`
- `docs/handoffs/SP-002.md`
- `docs/handoffs/SP-004.md`

## 2. Exit criteria & high-risk invariants
1. **Raw Body Cryptographic Preservation:**
   - Raw request body must be preserved byte-for-byte in memory without JSON serializer reformatting or mutation.
   - All 5 PayPal transmission headers (`PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-SIG`, `PAYPAL-TRANSMISSION-TIME`) must be extracted case-insensitively.
2. **Authentication Decoupling:**
   - Webhook endpoint must NOT be protected by user auth, cookies, or session tokens.
   - PayPal servers must be able to POST directly to the webhook receiver.
3. **Entitlement Authority (`PAY-AUTH-01`):**
   - Unverified webhook events MUST NEVER mutate business state (`Subscription`, `SubscriptionPayment`, `SoulmateSession`, `SoulmateArtifact`).
   - If transmission headers are missing or signature verification fails, the request must be rejected with 4xx and leave all business tables untouched.
4. **PayPal Retry Semantics & Idempotency:**
   - Replaying the same webhook event ID must return `200 OK` (with `duplicate: True`) so PayPal halts its delivery retry loop.
   - Permanent client errors (malformed JSON, empty payload, missing IDs) must return `400 Bad Request` to avoid futile retry loops.
   - Unexpected operational exceptions must produce `500 Internal Server Error`, triggering PayPal's exponential retry schedule.

## 3. Implementation review & evidence

### 3.1 Raw Body Preservation
- **Inspection:** Inspected `backend/app/api/soulmate/webhooks.py` and `backend/app/soulmate/services/webhook_service.py`.
- **Finding:**
  - `raw_body = await request.body()` captures the incoming byte stream directly from Starlette.
  - `PayPalWebhookRawRequest.raw_body` stores the raw bytes unmodified.
  - Transmission headers are extracted using case-insensitive mapping in `PayPalWebhookHeaders.from_headers`.
- **Automated Evidence:** Verified by `test_raw_body_preserved_byte_for_byte` in `backend/tests/test_paypal_webhooks.py`.

### 3.2 Authentication Decoupling
- **Inspection:** Inspected `webhooks.py` route definitions.
- **Finding:**
  - No `verify_session_token`, cookie dependency, or route guards are attached to `POST /paypal`.
- **Automated Evidence:** Verified by `test_endpoint_unprotected_by_normal_user_auth` and `test_endpoint_mounted_at_both_canonical_and_alias_paths`.

### 3.3 Entitlement Authority (`PAY-AUTH-01`)
- **Inspection:** Inspected `PayPalWebhookService.process_webhook` in `backend/app/soulmate/services/webhook_service.py`.
- **Finding:**
  - If `require_verification` is True and headers are incomplete or `verifier.verify()` returns False, `WebhookVerificationError` (HTTP 400) is raised.
  - Zero writes are made to `subscriptions`, `subscription_payments`, or `soulmate_sessions`.
- **Automated Evidence:** Verified by `test_unverified_event_missing_headers_rejected_and_mutates_no_state`, `test_unverified_event_signature_failure_rejected_and_mutates_no_state`, and `test_http_endpoint_unverified_payment_completed_mutates_no_session`.

### 3.4 Idempotency & Retry Semantics
- **Inspection:** Inspected `process_webhook` database lookup and exception handling.
- **Finding:**
  - `select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event_id)` detects duplicate events.
  - Replays return `status="duplicate"`, `duplicate=True`, HTTP 200 without duplicate row insertion or business effects.
  - Unexpected internal errors yield HTTP 500, triggering PayPal retries.
- **Automated Evidence:** Verified by `test_idempotent_duplicate_event_returns_200_to_stop_paypal_retries`, `test_http_endpoint_duplicate_event_returns_200_duplicate_true`, and `test_http_endpoint_server_error_returns_500_for_paypal_retry`.

## 4. Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Webhook unit & integration tests | PASS | 15/15 passed in `backend/tests/test_paypal_webhooks.py` |
| Full backend regression | PASS | 356/356 tests passed |
| Frontend Vitest regression | PASS | 252/252 tests passed |
| Frontend typecheck & lint | PASS | 0 errors |

## 5. Review Conclusion
**PASS** — SP-404 satisfies all exit criteria and strictly enforces Invariant `PAY-AUTH-01`. Safe to proceed to `SP-405`.
