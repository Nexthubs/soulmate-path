# SP-401 — PayPal Product/Plan Provisioning High-Risk Review

- **Review result:** CONDITIONAL_PASS
- **Reviewer:** Antigravity Payment & High-Risk Reviewer
- **Date:** 2026-09-24
- **Reviewed branch/commit:** main (`dad93f5`)
- **Task source:** `TASK-BREAKDOWN.md` → `SP-401`
- **Context refs used:** DEV-SPEC §9.1–9.2, §22, §25 | Decisions: `PAY-01`, `PAY-02`, `PAY-AUTH-01` | Dependency handoffs: `SP-004`

## 1. Scope and handoffs reviewed
Required Task IDs:
- `SP-401` (PayPal Product/Plan provisioning)

Handoffs:
- `docs/handoffs/SP-401.md`

## 2. Exit criterion
Provision reusable PayPal billing objects for monthly subscription:
- Intro plan: paid first-month promotional billing phase, then recurring regular monthly phase;
- Standard plan if required by `PAY-02` policy;
- No per-user plan creation;
- Prices come from config/approved input (no hardcoded pricing per `PAY-01`);
- Plan cadence is strictly monthly;
- Renewal disclosure values match plan;
- Safe to re-run or clearly detects existing provisioned plan.

## 3. Current implementation evidence
The repository implements the reusable PayPal subscription foundation across the domain, service, and tooling layers:
1. **Domain Contract & Payloads (`backend/app/soulmate/domain/paypal_models.py`):**
   - Implements typed Pydantic models for catalog products, monthly billing cycles (`PayPalBillingCycle`), payment preferences, and structured plan verification (`PayPalPlanVerificationResult`).
2. **Provider Client & Security (`backend/app/soulmate/services/paypal_client.py`):**
   - Implements async `PayPalClient` supporting OAuth2 Client Credentials (`/v1/oauth2/token`) with token expiration caching and renewal.
   - Headers and payload transmission adhere to official PayPal REST Subscriptions v1 specification.
   - **Credential Hygiene:** Credentials are encrypted in HTTP Basic Authorization headers; exceptions (`PayPalAPIError`, `PayPalAuthError`) redact secrets, preventing API keys from leaking into loggers or exception traces.
3. **Canonical Plan Structure (DEV-SPEC §9.1.1 & §9.2):**
   - `build_intro_plan_payload`: Constructs 2 billing cycles:
     - Cycle 1: `TRIAL` tenure, sequence 1, total_cycles 1, `MONTH` x 1 cadence, fixed intro price.
     - Cycle 2: `REGULAR` tenure, sequence 2, total_cycles 0 (indefinite recurrence), `MONTH` x 1 cadence, fixed regular price.
     - Payment preferences: `auto_bill_outstanding=True`, `payment_failure_threshold=1`.
   - `build_standard_plan_payload`: Constructs 1 billing cycle:
     - Cycle 1: `REGULAR` tenure, sequence 1, total_cycles 0, `MONTH` x 1 cadence, fixed regular price.
4. **Cadence & Invariant Verification (`PayPalProvisioningService.verify_plan`):**
   - Enforces status `ACTIVE`.
   - Rejects non-monthly cadences (`interval_unit != 'MONTH'` or `interval_count != 1`).
   - Verifies sequence order, cycle tenure types, and currency match.
5. **Disclosure Parity (`verify_disclosures_match_plan`):**
   - Programmatically verifies that `today_text` contains intro price and `renewal_text` contains regular price in agreement with `build_subscription_offer`.
6. **Idempotency & Re-run Safety:**
   - Provisioning queries existing products and plans before creation; re-running with existing matching objects executes 0 mutation POST requests.
   - Architectural invariant: Plans are reusable billing templates, never created per-user.
7. **CLI Tooling (`backend/scripts/provision_paypal.py`):**
   - Supports `--dry-run` inspection, Sandbox provisioning, and `--verify-only` validation.
   - Enforces Decision `PAY-01`: Fails fast if pricing is omitted or non-positive; refuses to guess production values.

## 4. Accepted contract checkpoint
- **API:** Internal service layer additions for PayPal REST interactions.
- **Types / schemas:** Pydantic v2 schemas in `app.soulmate.domain.paypal_models`.
- **Configuration:** Emits `.env` variables (`PAYPAL_PRODUCT_ID`, `PAYPAL_SOULMATE_INTRO_PLAN_ID`, `PAYPAL_SOULMATE_STANDARD_PLAN_ID`, `SOULMATE_CURRENCY`, `SOULMATE_INTRO_PRICE`, `SOULMATE_REGULAR_PRICE`).
- **DB / migration:** None (PayPal plans are provider-hosted billing objects).

## 5. Required evidence checklist
- [x] Prices come from config/approved input: Decimal validation verified; missing prices fail fast per `PAY-01`.
- [x] Plan cadence is monthly: Enforced across all cycles (`interval_unit == 'MONTH'`, `interval_count == 1`).
- [x] Renewal disclosure values match plan: `verify_disclosures_match_plan` PASS.
- [x] Safe to re-run / detects existing plan: Re-run idempotency verified in `test_provisioning_service_idempotent_reuses_existing_matching_objects` (0 POST mutations). Concurrency safety verified in `test_provisioning_service_concurrency_safety` (5 concurrent tasks create 1 plan).
- [x] Config output for Product ID / Plan ID(s): `.env` snippet generation verified in summary and CLI.
- [ ] Live Sandbox provider verification: `NOT_RUN` (Real PayPal Sandbox credentials `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` are not configured in the local workspace; automated mock verification passed 15/15 tests).

## 6. Test / manual / provider evidence
| Check | Result | Evidence/notes |
|---|---|---|
| `pytest backend/tests/test_paypal_provisioning.py` | PASS | 15/15 automated tests passing (payloads, cadence, disclosures, idempotency, auth caching, concurrency safety) |
| Full backend test suite (`pytest`) | PASS | 331/331 automated tests passing |
| Full frontend test suite (`vitest run --run`) | PASS | 236/236 automated tests passing |
| Frontend Typecheck & Lint | PASS | 0 Errors, 0 Warnings |
| Offline CLI Dry Run | PASS | Exact DEV-SPEC §9.1.1 & §9.2 payloads verified offline (with `setup_fee_failure_action` omitted); 0 network calls |
| CLI Price Validation | PASS | Fails fast with code 1 when prices missing or non-positive per Decision `PAY-01` |
| Idempotency re-run simulation | PASS | Verified in `test_provisioning_service_idempotent_reuses_existing_matching_objects` via `httpx.MockTransport` |
| Concurrency safety simulation (M-3) | PASS | Verified in `test_provisioning_service_concurrency_safety` (5 concurrent tasks serialize; exactly 1 product and 1 plan created) |
| Live PayPal Sandbox API call | NOT_RUN | PayPal Sandbox credentials not yet injected into local development environment. Per AGENTS.md §9, missing provider credentials cannot be converted into PASS. |

## 7. Findings
### P0
- none

### P1
- none

### P2
- none (M-1 credential injection, M-2 setup_fee_failure_action spec parity, and M-3 concurrency safety audit findings remediated and verified).

## 8. Deviations / unresolved decisions
- **M-1 Audit Remediation:** Test credentials centralized into `mock_paypal_credentials` pytest fixture in `backend/tests/test_paypal_provisioning.py`.
- **M-2 Audit Remediation:** Removed `setup_fee_failure_action` from `PayPalPaymentPreferences` and dumped payload with `exclude_none=True` to achieve 100% exact parity with DEV-SPEC §9.1.1 lines 1126-1129.
- **M-3 Audit Remediation:** Added `asyncio.Lock` and deterministic `PayPal-Request-Id` to guarantee in-process and cross-instance concurrency safety, verified by automated test.
- Decision `PAY-01` remains OPEN: exact production prices are TBD. Code strictly relies on injected environment variables / CLI parameters and provides no hardcoded fallbacks.
- Decision `PAY-02` remains OPEN: standard recurring monthly plan is provisioned alongside intro plan to allow seamless policy resolution without re-provisioning.

## 9. Rollback / recovery notes
- Provisioned plans can be deactivated via `client.deactivate_plan(plan_id)` if pricing changes occur.
- Re-running provisioning with updated prices will create new plans and output updated IDs without altering existing subscriptions.

## 10. Conditions for pass
1. **Sandbox Credential Verification:** When real PayPal Sandbox credentials (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`) are provisioned, live execution of `python backend/scripts/provision_paypal.py --verify-only` must be executed and recorded before Milestone M2 exit (`SP-1002` / `RV-02`).
2. **Production Pricing Gate:** Decision `PAY-01` must be formally resolved with approved commercial pricing before production deployment (M6).

## 11. Next milestone handoff
- Safe API/schema/migration/config checkpoints: Reusable PayPal product and plan provisioning service and CLI tool established.
- Capabilities that remain disabled: Live PayPal checkout remains disabled pending `SP-402`–`SP-408` and credentials injection.
- Next safe Task IDs: `SP-402` (PayPal JS subscription checkout).

## 12. Review decision
```text
Result: CONDITIONAL_PASS
Reason: Reusable PayPal monthly subscription infrastructure, canonical 2-cycle intro plan payload, 1-cycle standard plan payload, monthly cadence checks, disclosure parity, and idempotency logic are fully implemented and verified with 100% green tests. Live Sandbox provider call is explicitly recorded as NOT_RUN pending local credentials injection, conditioning final M2 signoff.
Open P0: 0
Open P1: 0
Next milestone may start: WITH_CONDITIONS (Condition: Execute live Sandbox verification when credentials are provided in M2)
```

## 13. Post-review updates
- [x] `docs/handoffs/SP-401.md` updated with exact evidence and NOT_RUN provider status
- [x] `PROJECT-STATE.md` updated
- [x] `TASK-BREAKDOWN.md` updated
