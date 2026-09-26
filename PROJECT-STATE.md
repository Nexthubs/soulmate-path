# PROJECT-STATE.md — Soulmate Path

> **Purpose:** current operational truth only. Decision detail belongs in `DECISIONS.md`; technical detail belongs in DEV-SPEC.
> **Governance:** Soulmate Path v1.2

## 1. Current milestone

```text
Current milestone: M2 — Sandbox Revenue Ready
Status: BLOCKED — RV-01/RV-02 remediation pending independent review and post-fix acceptance
Latest review checkpoint: docs/reviews/RV-01-RV-02-REMEDIATION.md (BLOCKED; historical M2 PASS does not cover current changes)
```

Repository architecture & boundary (`SP-001`) completed and evidenced in `docs/handoffs/SP-001.md`.
Database migration foundation (`SP-002`) completed and evidenced in `docs/handoffs/SP-002.md`.
Canonical quiz config (`SP-003`) completed and evidenced in `docs/handoffs/SP-003.md`.
Environment & secrets baseline (`SP-004`) completed and evidenced in `docs/handoffs/SP-004.md`.
Error codes & request correlation (`SP-005`) completed and evidenced in `docs/handoffs/SP-005.md`.
Landing page (`SP-101`) completed and evidenced in `docs/handoffs/SP-101.md`.
Shared Quiz layout (`SP-102`) completed and evidenced in `docs/handoffs/SP-102.md`.
OptionCard variants (`SP-103`) completed and evidenced in `docs/handoffs/SP-103.md`.
Transition layout & interstitials (`SP-104`) completed and evidenced in `docs/handoffs/SP-104.md`.
Email capture variants (`SP-105`) completed and evidenced in `docs/handoffs/SP-105.md`.
Result cards fixture UI (`SP-106`) completed and evidenced in `docs/handoffs/SP-106.md`.
Sketch viewer fixture UI (`SP-107`) completed and evidenced in `docs/handoffs/SP-107.md`.
Report renderer fixture UI (`SP-108`) completed and evidenced in `docs/handoffs/SP-108.md`.
Session create / recover (`SP-201`) completed and evidenced in `docs/handoffs/SP-201.md`.
Answer upsert and validation (`SP-202`) completed and evidenced in `docs/handoffs/SP-202.md`.
Flow / next-step resolver (`SP-203`) completed and evidenced in `docs/handoffs/SP-203.md`.
DOB / Zodiac (`SP-204`) completed and evidenced in `docs/handoffs/SP-204.md`.
Normalized Soulmate Profile builder (`SP-205`) completed and evidenced in `docs/handoffs/SP-205.md`.
Interstitial answer storage (`SP-206`) completed and evidenced in `docs/handoffs/SP-206.md`.
Connect Quiz UI to live APIs (`SP-207`) completed and evidenced in `docs/handoffs/SP-207.md`.
Email save / normalize / bind identity (`SP-301`) completed and evidenced in `docs/handoffs/SP-301.md`.
Email summary API/view model (`SP-302`) completed and evidenced in `docs/handoffs/SP-302.md`.
Subscribe offer/config API (`SP-303`) completed and evidenced in `docs/handoffs/SP-303.md`.
Route guards (`SP-304`) completed and evidenced in `docs/handoffs/SP-304.md`.
*(Note: WAVE 3 is now 100% complete)*
PayPal Product/Plan provisioning (`SP-401`) completed and evidenced in `docs/handoffs/SP-401.md`.
PayPal JS subscription checkout (`SP-402`) completed and evidenced in `docs/handoffs/SP-402.md`.
Confirm subscription API (`SP-403`) under remediation review; evidence in `docs/handoffs/SP-403.md`.
PayPal webhook endpoint with raw body (`SP-404`) completed and evidenced in `docs/handoffs/SP-404.md`.
PayPal webhook signature verification (`SP-405`) completed and evidenced in `docs/handoffs/SP-405.md`.
Event idempotency and out-of-order handling (`SP-406`) under remediation review; evidence in `docs/handoffs/SP-406.md`.
Payment ledger (`SP-407`) under remediation review; evidence in `docs/handoffs/SP-407.md`.
Subscription reconciliation/state mapping (`SP-408`) under remediation review; evidence in `docs/handoffs/SP-408.md`.
Cancellation and Settings action (`SP-409`) completed and evidenced in `docs/handoffs/SP-409.md`.
Payment-processing frontend state (`SP-410`) completed and evidenced in `docs/handoffs/SP-410.md`.
*(Wave 4 affected payment tasks returned to REVIEW; see RV remediation.)*
Artifact entitlement rows on first payment (`SP-501`) under remediation review; evidence in `docs/handoffs/SP-501.md`.
12h/24h status derivation (`SP-502`) under remediation review; evidence in `docs/handoffs/SP-502.md`.
Result aggregate API (`SP-503`) under remediation review; evidence in `docs/handoffs/SP-503.md`.
Frontend countdown using server time (`SP-504`) completed and evidenced in `docs/handoffs/SP-504.md`.
Result polling/refetch strategy (`SP-505`) completed and evidenced in `docs/handoffs/SP-505.md`.
*(Wave 5 SP-501..503 returned to REVIEW after RV remediation; M3 is not accepted.)*

## 2. Milestone status

| Milestone | Status | Review artifact |
|---|---|---|
| M1 Quiz Funnel Ready | PASS | `docs/reviews/M1-QUIZ-FUNNEL-REVIEW.md` |
| M2 Sandbox Revenue Ready | BLOCKED | `docs/reviews/M2-PAYPAL-SANDBOX-REVIEW.md` |
| M3 Entitlement / Result Ready | BLOCKED | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` |
| M4 Sketch Ready | NOT_STARTED | `docs/reviews/M4-SKETCH-REVIEW.md` |
| M5 Report Scaffold Ready | NOT_STARTED | `docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md` |
| M6 Production Ready | NOT_STARTED | `docs/reviews/M6-PRODUCTION-READINESS-REVIEW.md` |

## 3. Active / blocked work

Active tasks: RV-01 / RV-02 Critical/High remediation implemented, awaiting independent re-review and required post-fix provider evidence. Affected SP-403/406/407/408/501/502/503 are REVIEW. See `docs/reviews/RV-01-RV-02-REMEDIATION.md`.

Blocking decision IDs:

| Decision | Blocks |
|---|---|
| PAY-01 | PayPal production pricing / M6 |
| PAY-02 | re-subscription intro-price policy |
| AGE-01 | final DOB/legal rule |
| COPY-02 | complete Transition-2 production copy |
| COPY-03 | final Transition-4 dynamic behavior |
| REPORT-01 / REPORT-02 | production Report generation / SP-706 / M6 |
| RECOVERY-01 | same-email second paid session Sketch recovery path; gates PAY-02 resolution away from `blocked` |
| PROMPT-01 | future Sketch input-quality change |
| DOMAIN-01 | canonical production URLs |
| LEGAL-01 | production testimonials/statistics |

Details and current handling → `DECISIONS.md`.

## 4. Contract checkpoints

```text
Quiz config: soulmate-quiz-v1 (canonical JSON & seeded in DB soulmate_quiz_versions)
DB migration: 0005_legacy_session_status (head) applied to shared dev and verified round-trip in disposable PostgreSQL; 0004 added provider/billing ordering checkpoints, 0005 normalized legacy post-payment session status to SUBSCRIBED
Config checkpoint: DEV-SPEC §22 groups verified, centralized Decimal pricing, RFC 1123 domain syntax check, multi-layer frontend gate
API checkpoint: DEV-SPEC v1.2 baseline; error taxonomy, correlation middleware, and structured logging established (SP-005)
Payment provider: PayPal monthly subscription with intro first month + regular monthly renewal
Sketch target model: gpt-image-2 via provider adapter
Report production provider: disabled / decision pending
```

## 5. Production-disabled

- PayPal production checkout until required pricing/config/provider verification is complete.
- Production Report AI generation until `REPORT-01/02` are RESOLVED.
- Unapproved/fake testimonials or unsubstantiated statistics.

## 6. Next safe tasks

```text
1. Independently re-review RV-01/RV-02 repairs and obtain required post-fix provider evidence.
2. Reassess M2/M3 gates; no Wave 6 work is authorized by this repair.
```

## 7. Update rule

Keep this file short. Update only when milestone/status, critical blockers, accepted checkpoints, production-disabled capabilities, latest review, or next safe work changes.
