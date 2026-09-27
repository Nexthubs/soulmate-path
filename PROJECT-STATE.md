# PROJECT-STATE.md — Soulmate Path

> **Purpose:** current operational truth only. Decision detail belongs in `DECISIONS.md`; technical detail belongs in DEV-SPEC.
> **Governance:** Soulmate Path v1.2

## 1. Current milestone

```text
Current milestone: M5 — Report Scaffold Ready (Wave 7 complete, ready for independent review)
Status: READY_FOR_REVIEW (SP-701..705 DONE 2026-09-27; SP-706 BLOCKED on REPORT-01/02)
Latest accepted review: docs/reviews/M4-SKETCH-REVIEW.md (RV-03 PASS; M4 PASS)
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
Confirm subscription API (`SP-403`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-403.md`).
PayPal webhook endpoint with raw body (`SP-404`) completed and evidenced in `docs/handoffs/SP-404.md`.
PayPal webhook signature verification (`SP-405`) completed and evidenced in `docs/handoffs/SP-405.md`.
Event idempotency and out-of-order handling (`SP-406`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-406.md`).
Payment ledger (`SP-407`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-407.md`).
Subscription reconciliation/state mapping (`SP-408`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-408.md`).
Cancellation and Settings action (`SP-409`) completed and evidenced in `docs/handoffs/SP-409.md`.
Payment-processing frontend state (`SP-410`) completed and evidenced in `docs/handoffs/SP-410.md`.
*(Wave 4 is 100% complete — RV remediation accepted 2026-09-26 with live provider evidence.)*
Artifact entitlement rows on first payment (`SP-501`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-501.md`).
12h/24h status derivation (`SP-502`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-502.md`).
Result aggregate API (`SP-503`) completed; RV remediation accepted 2026-09-26 (`docs/handoffs/SP-503.md`).
Frontend countdown using server time (`SP-504`) completed and evidenced in `docs/handoffs/SP-504.md`.
Result polling/refetch strategy (`SP-505`) completed and evidenced in `docs/handoffs/SP-505.md`.
*(Note: WAVE 5 is 100% complete — SP-501..505 DONE; M3 CONDITIONAL_PASS 2026-09-26.)*
Versioned Sketch prompt template (`SP-601`) completed and evidenced in `docs/handoffs/SP-601.md`.
OpenAI image provider adapter (`SP-602`) completed and evidenced in `docs/handoffs/SP-602.md` (live-provider acceptance deferred to M4 gate — no credentials in dev).
Generation queue / worker (`SP-603`) completed and evidenced in `docs/handoffs/SP-603.md` (DB-backed queue on ai_generation_jobs, in-process workers, POST /artifacts/sketch/generate).
Retry / idempotency (`SP-604`) completed and evidenced in `docs/handoffs/SP-604.md` (two-phase claims, bounded exponential backoff, stale-claim reclamation, 20-concurrent trigger test passed).
Durable object storage (`SP-605`) completed and evidenced in `docs/handoffs/SP-605.md` (S3-compatible ObjectStorageSink via boto3; §11.7 keys; MIME/size validation; live upload deferred to M4 gate).
One-email-one-sketch constraint (`SP-606`) completed and evidenced in `docs/handoffs/SP-606.md` (identity-level generation convergence on email_normalized; DB constraint proven; cross-session read isolation preserved per RECOVERY-01).
Live Sketch page states (`SP-607`) completed and evidenced in `docs/handoffs/SP-607.md` (GET /artifacts/sketch asset URL, frontend live state machine, bounded polling, locked→Result routing; current private signed-URL policy is `ASSET-ACCESS-01`).
*(Note: WAVE 6 is 100% complete — SP-601..607 DONE, 2026-09-26.)*
`ReportV1` schema (`SP-701`) completed and evidenced in `docs/handoffs/SP-701.md` (canonical versioned content contract + plain-text content policy; REPORT-01/02 remain OPEN, production Report generation still disabled).
Report persistence (`SP-702`) completed and evidenced in `docs/handoffs/SP-702.md` (validated content_json on the session-scoped REPORT artifact row, no-clobber canonical save, GET /api/soulmate/artifacts/report with ownership + unlock gating; §13.3 OpenAI-compatible provider env keys added per owner direction, generation still disabled).
Report renderer parity (`SP-703`) completed and evidenced in `docs/handoffs/SP-703.md` (canonical contract moved to frontend domain layer with runtime validation mirroring the backend policy; ReportRenderer consumes only validated ReportV1 with a fail-safe fallback state; Figma 102:1358 parity styles untouched).
Report generation provider interface (`SP-704`) completed and evidenced in `docs/handoffs/SP-704.md` (pluggable `SoulmateReportGenerator` protocol; mock provider + owner-directed OpenAI-compatible adapter over §13.3 config; versioned prompt-template machinery with NO production template shipped — missing template fails closed; factory default disabled).
Report mock fixture (`SP-705`) completed and evidenced in `docs/handoffs/SP-705.md` (canonical `[MOCK]`-labeled fixture as single source of truth for the mock provider + backend E2E + frontend renderer tests; store→retrieve chain proven; dev env configured with OpenAI-compatible endpoint and gemma-4-26b, switch stays off).
*(Note: WAVE 7 is 100% complete — SP-701..705 DONE, 2026-09-27. M5 is ready for its independent review; SP-706 stays BLOCKED on REPORT-01/02.)*

## 2. Milestone status

| Milestone | Status | Review artifact |
|---|---|---|
| M1 Quiz Funnel Ready | PASS | `docs/reviews/M1-QUIZ-FUNNEL-REVIEW.md` |
| M2 Sandbox Revenue Ready | PASS (restored post-RV-remediation) | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` §6 |
| M3 Entitlement / Result Ready | CONDITIONAL_PASS | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` |
| M4 Sketch Ready | PASS — COMPLETE (RV-03, 2026-09-27) | `docs/reviews/M4-SKETCH-REVIEW.md` |
| M5 Report Scaffold Ready | READY_FOR_REVIEW (Wave 7 complete: SP-701..705 DONE) | `docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md` |
| M6 Production Ready | NOT_STARTED | `docs/reviews/M6-PRODUCTION-READINESS-REVIEW.md` |

## 3. Active / blocked work

Active tasks: RV-03 and M4 PASS on the reviewed code (`docs/reviews/M4-SKETCH-REVIEW.md`). H-02 claim-budget bypass is fixed and PostgreSQL regressions pass; M-02's unavoidable response-before-commit audit gap is documented. `ASSET-ACCESS-01` is enforced in production config; the current R2 object's former public URL returns 403 and its one-hour signed URL returns 200. The prior paid flow remains the live generation evidence; a fresh reviewer-run purchase, live retry, 12-hour wait and gate-subscription webhook replay remain NOT_RUN. M2 remains PASS and M3 CONDITIONAL_PASS.

Blocking decision IDs:

| Decision | Blocks |
|---|---|
| PAY-01 | PayPal production pricing / M6 |
| PAY-02 | re-subscription intro-price policy |
| AGE-01 | final DOB/legal rule |
| COPY-02 | complete Transition-2 production copy |
| COPY-03 | final Transition-4 dynamic behavior |
| REPORT-01 / REPORT-02 | production Report generation / SP-706 / M6 |
| RECOVERY-01 | same-email second paid session Sketch recovery path; 2026-09-27 owner ruling: session-scoped read isolation is INTENTIONAL (`不得恢复裸邮箱跨会话读取`), verified-identity recovery deferred to a future iteration; still gates PAY-02 resolution away from `blocked` |
| PROMPT-01 | future Sketch input-quality change |
| DOMAIN-01 | canonical production URLs |
| LEGAL-01 | production testimonials/statistics |

Details and current handling → `DECISIONS.md`.

## 4. Contract checkpoints

```text
Quiz config: soulmate-quiz-v1 (canonical JSON & seeded in DB soulmate_quiz_versions)
DB migration: 0005_legacy_session_status (head) applied to shared dev and verified round-trip in disposable PostgreSQL; 0004 added provider/billing ordering checkpoints, 0005 normalized legacy post-payment session status to SUBSCRIBED
Config checkpoint: DEV-SPEC §22 groups verified, centralized Decimal pricing, RFC 1123 domain syntax check, multi-layer frontend gate; §13.3 report provider env configured in dev (litellm.giaogiao.work / gemma-4-26b / key set; provider switch stays empty per REPORT-01/02)
API checkpoint: DEV-SPEC v1.2 baseline; error taxonomy, correlation middleware, and structured logging established (SP-005); report scaffold endpoints added (SP-702 GET /artifacts/report)
Payment provider: PayPal monthly subscription with intro first month + regular monthly renewal
Sketch target model: gpt-image-2 via provider adapter
Sketch production asset access: ASSET-ACCESS-01 chooses one-hour presigned URLs; current dev R2 origin private-read smoke PASS; future production bucket requires M6 verification
Report production provider: disabled / decision pending (SP-704 adapter + template machinery ready; SP-706 BLOCKED on REPORT-01/02)
```

## 5. Production-disabled

- PayPal production checkout until required pricing/config/provider verification is complete.
- Production Report AI generation until `REPORT-01/02` are RESOLVED.
- Unapproved/fake testimonials or unsubstantiated statistics.

## 6. Next safe tasks

```text
1. Keep M4's signed-only storage rule for deployment; M6 must recheck the actual production bucket, DNS and old public paths. The owner should check other consumers of the now-private shared `morii` bucket (`anima/`, `rmbg/`, root objects).
2. Follow the next task in `TASK-BREAKDOWN.md` when separately authorized. For any live PayPal webhook recheck, bind the backend on the WireGuard-reachable interface. Keep workers disabled or use the disposable PostgreSQL test runner for backend tests.
```
