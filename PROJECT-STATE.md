# PROJECT-STATE.md — Soulmate Path

> **Purpose:** current operational truth only. Decision detail belongs in `DECISIONS.md`; technical detail belongs in DEV-SPEC.
> **Governance:** Soulmate Path v1.2

## 1. Current milestone

```text
Current milestone: PRE-IMPLEMENTATION / M0
Status: IN_PROGRESS
Latest accepted review: docs/reviews/SP-002-HIGH-RISK-REVIEW.md (PASS)
```

Repository architecture & boundary (`SP-001`) completed and evidenced in `docs/handoffs/SP-001.md`.
Database migration foundation (`SP-002`) completed and evidenced in `docs/handoffs/SP-002.md`.
Canonical quiz config (`SP-003`) completed and evidenced in `docs/handoffs/SP-003.md`.
Environment & secrets baseline (`SP-004`) completed and evidenced in `docs/handoffs/SP-004.md`.
Error codes & request correlation (`SP-005`) completed and evidenced in `docs/handoffs/SP-005.md`.

## 2. Milestone status

| Milestone | Status | Review artifact |
|---|---|---|
| M1 Quiz Funnel Ready | NOT_STARTED | `docs/reviews/M1-QUIZ-FUNNEL-REVIEW.md` |
| M2 Sandbox Revenue Ready | NOT_STARTED | `docs/reviews/M2-PAYPAL-SANDBOX-REVIEW.md` |
| M3 Entitlement / Result Ready | NOT_STARTED | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` |
| M4 Sketch Ready | NOT_STARTED | `docs/reviews/M4-SKETCH-REVIEW.md` |
| M5 Report Scaffold Ready | NOT_STARTED | `docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md` |
| M6 Production Ready | NOT_STARTED | `docs/reviews/M6-PRODUCTION-READINESS-REVIEW.md` |

## 3. Active / blocked work

Active tasks: SP-101 (Session / state machine / profile service), SP-201 (Quiz engine UI / step framework).

Blocking decision IDs:

| Decision | Blocks |
|---|---|
| PAY-01 | PayPal production pricing / M6 |
| PAY-02 | re-subscription intro-price policy |
| AGE-01 | final DOB/legal rule |
| COPY-02 | complete Transition-2 production copy |
| COPY-03 | final Transition-4 dynamic behavior |
| REPORT-01 / REPORT-02 | production Report generation / SP-706 / M6 |
| PROMPT-01 | future Sketch input-quality change |
| DOMAIN-01 | canonical production URLs |
| LEGAL-01 | production testimonials/statistics |

Details and current handling → `DECISIONS.md`.

## 4. Contract checkpoints

```text
Quiz config: soulmate-quiz-v1 (canonical JSON & seeded in DB soulmate_quiz_versions)
DB migration checkpoint: 0002_add_indexes (Alembic schema with 9 tables, foreign key/query indexes, and high-risk invariants)
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
1. SP-101 — session / state machine / profile service
2. SP-201 — quiz engine UI / step framework
```

Do not fan out broad implementation until SP-001 documents the repository's real stack and reusable abstractions.

## 7. Update rule

Keep this file short. Update only when milestone/status, critical blockers, accepted checkpoints, production-disabled capabilities, latest review, or next safe work changes.
