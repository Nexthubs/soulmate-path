# PROJECT-STATE.md — Soulmate Path

> **Purpose:** current operational truth only. Decision detail belongs in `DECISIONS.md`; technical detail belongs in DEV-SPEC.
> **Governance:** Soulmate Path v1.2

## 1. Current milestone

```text
Current milestone: M5 — Report Scaffold Ready (remediation re-reviewed 2026-09-27)
Status: M5 PASS at 6e49409; REPORT-01/02 RESOLVED and SP-706 DONE (2026-09-27) — on_demand report generation LIVE in dev on gemma-4-26b with real-provider E2E evidence (docs/handoffs/SP-706.md)
Latest accepted review: docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md (M5 PASS; evidence limits recorded)
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
*(Note: WAVE 7 is 100% complete — SP-701..705 DONE, 2026-09-27. M5 scaffold re-review PASS; SP-706 stays BLOCKED on REPORT-01/02.)*
Drawer Soulmate entry (`SP-801`) completed and evidenced in `docs/handoffs/SP-801.md` (global AccountDrawer mounted once in the soulmate layout, `Soulmate Sketch` entry first with injectable sanitized destination defaulting to `/soulmate`; status-aware routing deferred to SP-802).
Status-aware Drawer destination (`SP-802`) completed and evidenced in `docs/handoffs/SP-802.md` (destination resolved per open from the SP-503 aggregate — 403→`/soulmate`, LOCKED→`/soulmate/result`, unlocked→`/soulmate/sketch`; cookie-only identity, real-backend E2E for all routing rows).
Subscription details in Settings (`SP-803`) completed and evidenced in `docs/handoffs/SP-803.md` (status response now carries `currency`/`regular_price` from the reconciled row; settings card shows plan/status/regular monthly price/next-billing-or-paid-through; full Figma page-chrome parity flagged for M6 QA).
Cancel action UI (`SP-804`) completed and evidenced in `docs/handoffs/SP-804.md` (extracted testable `CancelConfirmationDialog` with renewal-price quote + retention guarantee, in-flight re-entry guard, entry hidden once cancelled; success-path provider cancel covered by SP-409 tests + M3 gate live evidence).
Paid-through access display (`SP-805`) completed and evidenced in `docs/handoffs/SP-805.md` (`derivePaidAccessCopy` derives all access claims from actual reconciled state/dates; expired paid-through no longer claims "Active"; suspended/processing states carry no renewal promise; client clock used for display tense only per TIME-01).
Wave 8 audit remediation (Codex audit round 1: 3H+2M; round 2 re-review; round 3 2026-09-27): H-1 paid-subscription reconciliation, H-3 no-refund assertion removal, M-1 drawer fallback accepted in re-review; H-2/M-2 remainders fixed (plan-row price gating; unpaid access promises). Round-2 High on SP-805 RESOLVED by owner directive: `PAID-THROUGH-01` adopted. Round-3 (owner rulings): (a) `PAID-THROUGH-01` enforcement extended to the API layer — result aggregate, sketch/report generation triggers refuse a known-and-passed window; artifact reads keep COMPLETED content retrievable per §9.8; (b) `REFUND-01` RESOLVED — owner approved the provisional wording, shipped to the cancel dialog and cancelled-state card (paid subscriptions only). Latest SP-805 re-review fix: completed Sketch/Report pages and Settings links remain usable after expiry; cached ACTIVE at a crossed cycle boundary is reconciled with PayPal and cannot alone extend access (disposable PostgreSQL backend 843/843; frontend 394/394). Known evidence gap: real PayPal Sandbox success-path cancel E2E through the new dialog is NOT_RUN (owner-scheduled; runbook in docs/handoffs/SP-804.md).
*(Note: WAVE 8 is IN_PROGRESS — SP-802/805 DONE; SP-803/804 in REVIEW (fixes applied through round 3). All Wave 8 audit decisions now RESOLVED.)*
Funnel event contract and instrumentation (`SP-901`, Wave 9) DONE 2026-09-28 after audit remediation (`docs/handoffs/SP-901.md`): page views deduplicate by authorized session only for one component mount and fire again on re-entry; unlock events retain tab-session dedupe; Sketch view sends the persisted artifact version. Embedded email PII is redacted, stale cross-session responses are ignored, and first-payment confirmation emits after commit. Prior full isolated backend suite: 879/879 PASS; follow-up Sketch API: 13/13, frontend: 415/415, typecheck/lint PASS. Production analytics sink remains OPEN as `ANALYTICS-01` (default drops in production).
Generation metrics (`SP-902`, Wave 9) completed 2026-09-28 (`docs/handoffs/SP-902.md`): stable `generation_metric` structured-log stream (8 metrics: enqueue created/duplicate, queue latency, success, retry, user retry, final failure, stale reclaim) emitted for both sketch and report pipelines via `app/soulmate/metrics.py`; `GenerationMetricsService.summary()` provides read-only DB aggregation by job type (counts, retries_total, final failure rate, queue/generation latency stats). No worker state transitions changed. Evidence: disposable PostgreSQL backend 866/866; migration upgrade/downgrade/re-upgrade PASS.
Payment/webhook metrics (`SP-903`, Wave 9) completed 2026-09-28 (`docs/handoffs/SP-903.md`): stable allowlisted `payment_metric` structured-log stream covers verification and processing failures, duplicate events, first-payment confirmation latency, reconciliation mismatches, and safe payment-failure categories. No payment, webhook, or entitlement outcomes changed. Evidence: disposable PostgreSQL backend 872/872; migration upgrade/downgrade/re-upgrade PASS.
Alerts (`SP-904`, Wave 9) BLOCKED 2026-09-28 (`docs/handoffs/SP-904.md`): task requires the existing alerting platform, but no platform/configuration or alert thresholds/routing are recorded in the repo or connected tools. Do not create a replacement monitoring stack; resume after owner identifies the platform and policy.
Admin/support lookup (`SP-905`, Wave 9) DONE 2026-09-28 (`docs/handoffs/SP-905.md`): exact-key support lookup returns allowlisted status/timeline data; historical events carry only event-time statuses, current values are labeled as snapshots, and `timeline_history_complete=false` marks the retained history as partial. Email matching is normalized, body-only, and fails closed when ambiguous. A dedicated `SUPPORT_API_KEY` is required in production (see `SUPPORT-AUTH-01`).
Mobile/browser matrix (`SP-1001`, Wave 10) DONE 2026-09-28 (`docs/handoffs/SP-1001.md`): Chromium matrix at 390px baseline + 320/768/1280 across all user-facing routes — full input walk (quiz single/date/multi, Transition-5 modals, email, drawer), PayPal checkout UI rendered, unpaid/paid guard states verified; 22/22 routes×widths zero horizontal overflow. Entitlement visuals used a dev-DB QA fixture, fully deleted afterwards (not payment evidence). WebKit/real-device pass (desktop Safari, iOS Safari, Android Chrome) NOT_RUN — no WebKit/device tooling in this environment; no formal browser-support policy exists (owner TBD before M6). Follow-up owner-directed pass same day (`UI-COPY-01` RESOLVED in DECISIONS.md): all internal contract IDs removed from user-facing copy (backend API reasons/messages, frontend pages, [MOCK] fixture copies); tests now assert semantic copy; backend 880/880, frontend 415/415, typecheck/lint PASS, browser 390px re-verification clean.

## 2. Milestone status

| Milestone | Status | Review artifact |
|---|---|---|
| M1 Quiz Funnel Ready | PASS | `docs/reviews/M1-QUIZ-FUNNEL-REVIEW.md` |
| M2 Sandbox Revenue Ready | PASS (restored post-RV-remediation) | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` §6 |
| M3 Entitlement / Result Ready | CONDITIONAL_PASS | `docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md` |
| M4 Sketch Ready | PASS — COMPLETE (RV-03, 2026-09-27) | `docs/reviews/M4-SKETCH-REVIEW.md` |
| M5 Report Scaffold Ready | PASS — scaffold only (2026-09-27 re-review at `6e49409`) | `docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md` |
| M6 Production Ready | NOT_STARTED | `docs/reviews/M6-PRODUCTION-READINESS-REVIEW.md` |

## 3. Active / blocked work

Active gate: M5 scaffold PASS on the reviewed `6e49409` code (`docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md`); its browser, database and provider evidence limits are recorded there. REPORT-01 is RESOLVED (owner: on_demand + gemma-4-26b via OpenAI-compatible adapter) and SP-706 implementation is authorized; production go-live stays gated on REPORT-02 (owner to supply the prompt text). M4 PASS, M2 PASS and M3 CONDITIONAL_PASS remain unchanged.

Blocking decision IDs:

| Decision | Blocks |
|---|---|
| PAY-01 | PayPal production pricing / M6 |
| PAY-02 | re-subscription intro-price policy |
| AGE-01 | final DOB/legal rule |
| COPY-02 | complete Transition-2 production copy |
| COPY-03 | final Transition-4 dynamic behavior |
| (REFUND-01 RESOLVED 2026-09-27 — approved refund copy shipped; PAID-THROUGH-01 RESOLVED 2026-09-27 — guards+APIs honor `paid_through_at`; REPORT-01/02 RESOLVED; SP-706 DONE — remaining M6 gates: production provider config, real paid flow, PAY-01, DOMAIN-01) | M6 |
| RECOVERY-01 | same-email second paid session Sketch recovery path; 2026-09-27 owner ruling: session-scoped read isolation is INTENTIONAL (`不得恢复裸邮箱跨会话读取`), verified-identity recovery deferred to a future iteration; still gates PAY-02 resolution away from `blocked` |
| PROMPT-01 | future Sketch input-quality change |
| DOMAIN-01 | canonical production URLs |
| LEGAL-01 | production testimonials/statistics |

Details and current handling → `DECISIONS.md`.

## 4. Contract checkpoints

```text
Quiz config: soulmate-quiz-v1 (canonical JSON & seeded in DB soulmate_quiz_versions)
DB migration: 0006_price_verification (head) applied to shared dev and verified round-trip; 0005 normalized legacy post-payment session status to SUBSCRIBED; 0006 adds subscriptions.price_verified_at for provider price snapshot provenance (Wave 8 audit H-2)
Config checkpoint: DEV-SPEC §22 groups verified, centralized Decimal pricing, RFC 1123 domain syntax check, multi-layer frontend gate; §13.3 report provider env configured in dev (litellm.giaogiao.work / gemma-4-26b / key set; provider switch stays empty per REPORT-01/02)
API checkpoint: DEV-SPEC v1.2 baseline; error taxonomy, correlation middleware, and structured logging established (SP-005); report scaffold endpoints added (SP-702 GET /artifacts/report)
Payment provider: PayPal monthly subscription with intro first month + regular monthly renewal
Sketch target model: gpt-image-2 via provider adapter
Sketch production asset access: ASSET-ACCESS-01 chooses one-hour presigned URLs; current dev R2 origin private-read smoke PASS; future production bucket requires M6 verification
Report production provider: ENABLED in dev (REPORT-01/02 RESOLVED; on_demand via SP-706 trigger/queue; v1 owner-approved prompt ba6e6e7e…; model gemma-4-26b); production deployment verification = M6
```

## 5. Production-disabled

- PayPal production checkout until required pricing/config/provider verification is complete.
- Unapproved/fake testimonials or unsubstantiated statistics.

## 6. Next safe tasks

```text
1. Report generation is live in dev (SP-706 DONE). M6 must verify production provider configuration, run a real paid-flow acceptance, reword-review READY/FAILED copy if needed, and re-check exact 390px visual parity. M6 must independently verify release configuration, exact 390px visual parity and a real paid flow. Release QA must also reword the Report page READY-state copy (it currently says the report is being prepared although generation is off — M5 re-review Low note).
2. WAVE 8 (authorized): SP-802/805 DONE (latest access re-review fix documented in docs/handoffs/SP-805.md); SP-803/804 in REVIEW after round-2 fixes (plan-row price gating; unpaid access promises; cancel-entry/renewal-sentence gating by subscription state). `REFUND-01` approved wording is shipped; real Sandbox cancel E2E owner-scheduled and NOT_RUN. Wave 9 implementation checkpoint PASS, owner-scoped to SP-901/902/903/905 (`docs/reviews/WAVE-9-ANALYTICS-OPERATIONS-REVIEW.md`); SP-904 (alerts) remains BLOCKED on existing platform/policy details (`docs/handoffs/SP-904.md`) and is explicitly excluded from this checkpoint. This does not represent full Wave 9 operational readiness or M6/release acceptance. M6 production readiness remains unpassed: release QA should also decide on full Figma parity for the Settings page chrome (see docs/handoffs/SP-803.md §9) and resolve ANALYTICS-01 (production analytics sink) before go-live.
3. Preserve M4's signed-only storage rule for deployment; M6 must recheck the production bucket and affected consumers. Follow later tasks only when separately authorized.
```
