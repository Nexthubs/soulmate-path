# M5 Remediation — H-01 / M-01 / M-02 / R-01

- **Date:** 2026-09-27
- **Reviewed target:** `main` `78f1dbe` (M5 review baseline)
- **Remediation target:** findings in [`M5-REPORT-SCAFFOLD-REVIEW.md`](M5-REPORT-SCAFFOLD-REVIEW.md) (Result: BLOCKED — 1 High, 2 Medium, 1 Medium risk)
- **Result:** all confirmed findings and the R-01 risk fixed with regression tests; the reviewer's NOT_RUN evidence gaps (isolated-PostgreSQL rerun, 390px browser render of stored content) closed by this remediation run. Production Report generation remains DISABLED (REPORT-01/02 OPEN; SP-706 BLOCKED).

## Fix map

| Finding | Fix | Regression tests |
|---|---|---|
| **H-01** — persisted Report cannot reach the Report page | `/soulmate/report` is live-wired: `api/report.ts` (`getReportStatus`, credentials include) → `useReportStatus` (single authoritative fetch + read-only retry) → §10.3 state machine (`deriveReportViewState`): LOCKED→redirect to Result, READY→preparing card, GENERATING→loading card, COMPLETED→stored validated content via the SP-703 renderer gate, FAILED→support card. Guard behavior mirrors the accepted sketch page (SP-607): server verdict gates access; dev `?fixture=true` preview unchanged. A COMPLETED status without content degrades to support — the Figma fixture is never substituted for user content. | `frontend/tests/report-live.test.tsx` (13 tests: §10.3 mapping, API client, 8 page states incl. IDOR-style guard denial, content-through-gate, invalid-content fallback, no-fixture-substitution) |
| **M-01** — mutated model instance bypasses revalidation | `parse_soulmate_report_v1` re-validates any `BaseModel` input through its serialized copy (`model_dump(by_alias=True, exclude_none=True)`) before `model_validate`, closing pydantic's same-class-instance pass-through. `save_completed_report` inherits the fix (it calls the parser) and still accepts model instances as a convenience. | `test_report_schema.py::TestM5Remediation::test_parse_revalidates_serialized_copy_of_model_instances`; `test_report_persistence.py::test_save_revalidates_mutated_model_instance_without_partial_write` (both boundaries, mutated `<script>` title rejected, no partial write, clean instance still saves) |
| **M-02** — backend/frontend disagree on blank optional `closing` | Unified to **normalize-to-absent on both sides**: backend `SoulmateReportV1._closing_blank_normalized_to_absent` (blank → `None`, excluded from persistence by `exclude_none`); frontend `parseSoulmateReportV1` treats a blank closing as absent instead of rejecting. Markup/script rejection still applies to non-blank closings on both stacks. | Backend: `test_blank_closing_normalizes_to_absent` (+ non-blank preserved). Frontend: `report-domain.test.ts` "cross-stack closing parity" — parses the exact backend serialization of a blank-closing payload (generated via the backend parser) and raw blank strings; markup closing still rejected |
| **R-01** — versioned rows selected without a version predicate | All report read/save/status queries pinned to `artifact_version='v1'` (`ReportService.get_report_artifact`, `save_completed_report` FOR UPDATE query, `ArtifactStatusService.get_artifact_statuses`). A future V2 row can never be selected; save fails closed (`NotFoundError`) when no V1 row exists. | `test_version_predicates_pin_reads_saves_and_statuses_to_v1` (V1+V2 rows coexist → read returns V1, save writes V1 and leaves V2 untouched, statuses derive from V1); `test_save_fails_closed_when_only_non_v1_row_exists` |

## Independent verification run (this remediation)

| Check | Result | Notes |
|---|---|---|
| Full backend suite in an **isolated disposable PostgreSQL** (`backend/scripts/test_isolated.py`: create generated DB → alembic upgrade/downgrade/re-upgrade cycle → quiz seed → pytest → drop DB) | **PASS 802/802** | closes the reviewer's "PostgreSQL persistence/retrieval rerun NOT_RUN" gap; includes all M5 report DB/API suites (uniqueness, concurrency, IDOR, 24h unlock gate) against a pristine database |
| Frontend suite | PASS 352/352 | includes 13 new `report-live` page tests |
| typecheck / lint / build | PASS / PASS / PASS | `/soulmate/report` prerenders (7.56 kB) |

## Live integration acceptance (H-01: stored fixture → API → 390px browser render)

Executed 2026-09-27 against the real dev stack (backend uvicorn on :8000 with workers disabled, frontend dev server):

1. Browser (390×844 viewport) opened `http://localhost:3001/soulmate`; from the page origin a real
   `POST /api/soulmate/sessions` (credentials: include) created session `ses_5e479a42aced37e51b3a5e04fe294bb1`
   and the backend set the HttpOnly `soulmate_sid` cookie (CORS allow-list + `allow_credentials=true`).
2. Seed script (`/tmp/m5_e2e_seed.py`, reproduced in §Commands) attached to that exact public_id:
   `SUBSCRIBED` status, `first_payment_at = now-30h`, REPORT `v1` placeholder with `unlock_at = first_payment+24h`
   (past), then persisted `MOCK_REPORT_JSON` via `ReportService.save_completed_report` (provider/model/prompt_version=mock).
3. Navigated the same tab to `/soulmate/report`: the page live-fetched `GET /api/soulmate/artifacts/report`
   with the session cookie and rendered the STORED `[MOCK]` content — DOM snapshot shows the full editorial
   structure (H1 title, intro, numbered sections 01./02., points list with lead-in titles, closing, ✦ ✦ ✦ end mark).
4. Full-page screenshot archived: [`docs/artifacts/m5_h01_live_report_390px.png`](../artifacts/m5_h01_live_report_390px.png).
5. Cleanup: seeded rows (email `sp_m5e2e_108c4735@example.com`) deleted from the shared dev DB; dev servers stopped.

This is the single application flow the M5 exit criterion requires: **stored validated fixture data → authorized API read → 390px page render**, with production generation still off.

## Commands (reproduction)

```bash
# 1. isolated-DB full backend suite
backend/.venv/bin/python backend/scripts/test_isolated.py

# 2. frontend checks
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend run build

# 3. live integration (backend + frontend dev servers running)
backend/.venv/bin/python /tmp/m5_e2e_seed.py <public_id>   # seed entitlement + fixture past unlock
# browser at 390px: POST /api/soulmate/sessions from the app origin, then open /soulmate/report
backend/.venv/bin/python /tmp/m5_e2e_seed.py --cleanup <email>   # remove seeded rows
```

## Not addressed (unchanged scope boundaries)

- Live OpenAI-compatible generation (NOT_RUN, **outside M5** per the review): REPORT-01/02 remain OPEN; SP-706 stays BLOCKED; `SOULMATE_REPORT_PROVIDER` stays empty. Dev env has endpoint/model/key configured (litellm.giaogiao.work / gemma-4-26b) but the switch is off.
- Real paid-session purchase flow through PayPal (M4/M5 reviewer-run purchase remains NOT_RUN as before; the remediation used a seeded server-side entitlement, which is the same simulated-payment pattern the accepted sketch tests use).
- A fresh Figma-vs-browser pixel diff beyond this run's screenshot: the renderer styles are unchanged since SP-108's verified parity; the archived screenshot documents the current 390px rendering.

## Disposition

```text
H-01: FIXED + live-flow evidence (store → API → 390px render)
M-01: FIXED (parser + save boundary revalidation) + regression tests
M-02: FIXED (normalize-to-absent on both stacks) + cross-stack test
R-01: FIXED (V1 pinning on read/save/status) + regression tests
Isolated PostgreSQL rerun: PASS 802/802
390px stored-content browser render: PASS (archived screenshot)
Production Report generation: still DISABLED (REPORT-01/02 OPEN)
Recommendation: M5 gate is ready for re-review on this remediation
```
