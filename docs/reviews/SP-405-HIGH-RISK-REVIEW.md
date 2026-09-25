# SP-405 — PayPal Webhook Signature Verification High-Risk Review

- **Review result:** PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-24
- **Reviewed branch/commit:** main / working-tree checkpoint
- **Task source:** `TASK-BREAKDOWN.md` → `SP-405`
- **Context refs used:** DEV-SPEC §9.6 | Decisions: `PAY-AUTH-01` | Dependency handoffs: `SP-404`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-405` (Webhook signature verification)

Handoffs:
- `docs/handoffs/SP-405.md`
- `docs/handoffs/SP-404.md`

## 2. Exit criteria & high-risk invariants
1. **Official Verification Mechanism (DEV-SPEC §9.6):**
   - Must use PayPal's official REST verification API (`POST /v1/notifications/verify-webhook-signature`).
   - Request payload must faithfully map `auth_algo`, `cert_url`, `transmission_id`, `transmission_sig`, `transmission_time`, `webhook_id`, and `webhook_event`.
2. **Defense-in-Depth Origin Validation:**
   - Must validate `cert_url` before triggering outbound network requests to prevent Server-Side Request Forgery (SSRF) and certificate poisoning.
   - Requires `https` scheme, standard port (None or 443), and strict domain origin (`paypal.com` or `*.paypal.com`).
3. **Safe Error Handling & Logging Security:**
   - Verification failures must be rejected with HTTP 400 `WebhookVerificationError`.
   - Logs must sanitize sensitive credentials, bearer tokens, and customer PII, while capturing event ID, transmission ID, and error category for operational debugging.
4. **Entitlement Authority Invariant (`PAY-AUTH-01`):**
   - Forged, tampered, or unverified webhook events must NEVER mutate business state (`Subscription`, `SubscriptionPayment`, `SoulmateSession`, `SoulmateArtifact`).
   - Unverified events must not be marked as verified in `paypal_webhook_events`.

## 3. Implementation review & evidence

### 3.1 Official Verification Mechanism
- **Inspection:** Inspected `backend/app/soulmate/services/paypal_client.py` (`verify_webhook_signature`).
- **Finding:**
  - Invokes `POST /v1/notifications/verify-webhook-signature` on the configured PayPal environment (sandbox/production).
  - Passes full payload structure with all transmission headers and `webhook_event` dict.
  - Parses `data.get("verification_status") == "SUCCESS"` to return a boolean result.
- **Automated Evidence:**
  - `test_paypal_client_verify_signature_payload_and_success` in `backend/tests/test_paypal_webhook_verifier.py`.
  - `test_paypal_client_verify_signature_failure_status`.
  - `test_paypal_client_verify_signature_api_error_returns_false`.

### 3.2 Defense-in-Depth Origin Validation
- **Inspection:** Inspected `is_valid_paypal_cert_url` in `backend/app/soulmate/services/webhook_verifier.py`.
- **Finding:**
  - Enforces `parsed.scheme.lower() == "https"`.
  - Enforces `parsed.port in (None, 443)`.
  - Enforces `hostname == "paypal.com" or hostname.endswith(".paypal.com")`.
  - Fails fast on malformed, HTTP, custom port, or phishing URLs without calling PayPal API.
- **Automated Evidence:**
  - `test_cert_url_validation` parameterized test with 18 distinct valid/invalid vectors.
  - `test_verifier_rejects_untrusted_cert_url`.
  - `test_http_endpoint_rejects_forged_cert_url_with_400`.

### 3.3 Safe Error Handling & Logging
- **Inspection:** Inspected `PayPalWebhookVerifier.verify` and error paths.
- **Finding:**
  - Rejection branches log `event_id`, `transmission_id`, `event_type`, and `error_code` without dumping `client_secret` or auth headers.
  - Network timeouts and unexpected exceptions are caught and logged at `ERROR` level while returning `False` gracefully.
  - Rejection produces standard `WebhookVerificationError` (HTTP 400 `VALIDATION_ERROR`).
- **Automated Evidence:**
  - `test_verifier_rejects_incomplete_transmission_headers`.
  - `test_verifier_network_exception_fails_safely`.

### 3.4 Entitlement Authority (`PAY-AUTH-01`)
- **Inspection:** Inspected end-to-end flow from `POST /api/webhooks/paypal` through `PayPalWebhookService.process_webhook`.
- **Finding:**
  - When an incoming webhook payload with forged signature arrives targeting an active session:
    - Verifier returns `False`.
    - `WebhookVerificationError` is raised.
    - Transaction is aborted before touching `SoulmateSession.subscription_success_at`, `Subscription`, or `SubscriptionPayment`.
    - No record is stored in `paypal_webhook_events`.
- **Automated Evidence:**
  - `test_invariant_pay_auth_01_forged_webhook_mutates_no_entities` in `backend/tests/test_paypal_webhook_verifier.py`.
  - `test_http_endpoint_verified_webhook_succeeds_and_persists`.

## 4. Verification Summary
| Check | Status | Evidence |
|---|---|---|
| Dedicated Verifier Unit & E2E tests | PASS | 30/30 passed in `backend/tests/test_paypal_webhook_verifier.py` (including H-1 fail-closed test) |
| Webhook endpoint tests | PASS | 15/15 passed in `backend/tests/test_paypal_webhooks.py` |
| Full backend regression | PASS | 385/385 passed in 11.00s |
| Frontend Vitest regression | PASS | 252/252 passed in 1.23s |
| Frontend typecheck & lint | PASS | 0 errors |

## 5. Review Conclusion
**PASS** — SP-405 satisfies all acceptance criteria, follows official PayPal verification contracts, enforces anti-SSRF defense-in-depth, and strictly upholds High-Risk Invariant `PAY-AUTH-01`. Safe to proceed to `SP-406` (Event idempotency and out-of-order handling).
