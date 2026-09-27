# M5 — Report Scaffold Ready independent review

- **Result:** BLOCKED
- **Reviewer/date:** Codex, 2026-09-27
- **Target:** `main` HEAD `78f1dbeacd456597055f49be7aa2890566ef9b58`; review-start `git status --short --branch` was `## main`, with no staged or unstaged diff.
- **Scope:** SP-701–705, their handoffs, the M5 gate, report code/tests, existing artifact migration, and the production-disabled boundary. This review changes no application code or migration.
- **Severity:** Critical/High/Medium/Low; confirmed findings, risks, and missing evidence are separated below.

## Scope and exit criterion

Required tasks SP-701–705 are marked `DONE` and have handoffs at `docs/handoffs/SP-701.md` through `SP-705.md`. `TASK-BREAKDOWN.md:1709-1731` owns the gate. Exact exit criterion: “Report can be stored/rendered from validated structured fixture data. Production generation may remain off.” `REPORT-01/02` remain `OPEN` (`DECISIONS.md:109-124`), so SP-706 and production generation remain blocked as intended.

## Confirmed findings

### H-01 — High: persisted Report cannot reach the Report page

- **Spec Requirement:** M5 exit requires Report fixture data to be stored and rendered; DEV-SPEC §13.2 requires a frontend renderer for persisted `content_json`, and §3 maps an entitled, 24-hour-unlocked user to `/soulmate/report` (`Soulmate-Path-DEV-SPEC-v1.2.md:189-215,1544-1563`; `TASK-BREAKDOWN.md:1709-1727`).
- **Actual Implementation:** `GET /api/soulmate/artifacts/report` can return validated `content`, but the production page never calls it. Its `isProduction` branch always returns a static “Soulmate Report Locked” card, regardless of successful guard verdict or stored `COMPLETED` content. The dev page renders the separate Figma fixture. Backend store→HTTP retrieval and frontend fixture→renderer are separate tests; none proves persisted bytes reach the user page. The SP-703 handoff explicitly defers live API wiring.
- **Evidence（路径与行号）:** `backend/app/api/soulmate/artifacts.py:161-193`; `frontend/src/app/soulmate/report/page.tsx:19-68`; `frontend/src/soulmate/components/report/ReportRenderer.tsx:23-41`; `frontend/tests/report-fixture.test.tsx:36-65`; `docs/handoffs/SP-703.md` §2/§10.
- **Recommended Fix:** Wire the page to the authorized report endpoint, handle `LOCKED/READY/GENERATING/COMPLETED/FAILED`, and pass only a `COMPLETED` response's validated `content` to `ReportRenderer`. Add a browser/API integration case in which a fixture is stored, retrieved under an entitled session after the server 24-hour gate, and rendered. Keep production generation disabled.

### M-01 — Medium: mutable model instance bypasses the backend validation boundary

- **Spec Requirement:** SP-701 rejects executable HTML/script content; SP-702 stores only validated ReportV1 content (`TASK-BREAKDOWN.md:1074-1108`; `Soulmate-Path-DEV-SPEC-v1.2.md:1544-1563`).
- **Actual Implementation:** `save_completed_report` accepts either a dictionary or a `SoulmateReportV1`. It calls `parse_soulmate_report_v1`, which passes an existing Pydantic model instance to `model_validate` without revalidating fields. A model validated once and then mutated to a `<script>` title is accepted and can be saved. The API's later read of the JSON revalidates and fails closed, so this is a persistence/availability defect rather than demonstrated XSS.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/report_service.py:58-83,100-114`; `backend/app/soulmate/domain/report.py:167-209,245-261`. Independent read-only Python reproduction: mutate a valid model's `title` to `<script>alert(1)</script>`; `parse_soulmate_report_v1(model)` returned that title without error. Existing schema tests exercise payload parsing but do not cover this mutated-instance path.
- **Recommended Fix:** Revalidate a serialized copy of model inputs (or make the model frozen with instance revalidation); add a regression test at both parser and save boundaries.

### M-02 — Medium: backend and frontend disagree on an optional closing

- **Spec Requirement:** One validated ReportV1 JSON contract must survive persistence and renderer validation (`Soulmate-Path-DEV-SPEC-v1.2.md:1544-1563`; `TASK-BREAKDOWN.md:1110-1127`).
- **Actual Implementation:** backend accepts `closing: ""` and whitespace-only strings, persists them, and may serve them after unlock. Frontend rejects either value as a nonblank string and displays “Report Unavailable” instead of the remaining valid sections. The canonical fixture has a nonblank closing, so existing tests miss this boundary.
- **Evidence（路径与行号）:** `backend/app/soulmate/domain/report.py:190-213`; `frontend/src/soulmate/domain/report.ts:195-201`; `frontend/src/soulmate/components/report/ReportRenderer.tsx:38-48,238-257`. Independent parser reproduction confirmed backend acceptance of both `""` and `"   "`.
- **Recommended Fix:** Align both validators: either reject blank optional closing on the backend or normalize it to absent on both sides; test backend-serialized content through the frontend parser.

## Risks requiring validation

### R-01 — Medium: versioned rows are selected without a version predicate

- **Spec Requirement:** SP-702 requires one canonical current V1 report; the DB permits one row per `(session_id, artifact_type, artifact_version)` (`TASK-BREAKDOWN.md:1095-1108`; `backend/alembic/versions/0001_initial_soulmate_schema.py:157-179`).
- **Actual Implementation:** the Report read/save queries and status map select by session/type only, with no `artifact_version='v1'` or deterministic ordering. Current creation code inserts V1 only, so no current wrong-row incident was observed. A later V2 row could make a V1 save/read/status select the wrong row.
- **Evidence（路径与行号）:** `backend/app/soulmate/services/report_service.py:44-55,85-93`; `backend/app/soulmate/services/status_service.py:49-75`; `backend/app/soulmate/services/subscription_service.py:266-283`; `backend/app/db/models/artifact.py:110-116`.
- **Recommended Fix:** Pin the V1 service/query to `artifact_version='v1'` and define current-version selection explicitly before adding another report version.

## Missing or limited real acceptance evidence

- **PostgreSQL persistence/retrieval rerun: NOT_RUN by this reviewer.** SP-702 and SP-705 handoffs report 19 and 7 passing DB/API tests, including uniqueness, concurrency, IDOR and unlock cases. These tests use `AsyncSessionLocal` and write database rows (`backend/tests/test_report_persistence.py:55-73,243-294,360-474`; `backend/tests/test_report_fixture.py:135-204`). To keep this audit read-only, I did not run them against the configured shared database or create/drop a disposable database. The migration and ORM both declare JSONB plus the `(session_id, artifact_type, artifact_version)` unique constraint (`backend/alembic/versions/0001_initial_soulmate_schema.py:157-179`; `backend/app/db/models/artifact.py:66-73,110-116`); no Wave 7 migration exists. This is source inspection and prior handoff evidence, not an independently repeated PostgreSQL acceptance.
- **390px current browser comparison to Figma `102:1358`: NOT_RUN.** SP-108 has an archived Figma screenshot (`docs/artifacts/figma_report_102_1358.png`), and SP-703 states the renderer styles were unchanged. Current tests inspect markup/classes; they are not a fresh 390px browser screenshot or pixel comparison (`docs/handoffs/SP-703.md` §6; `frontend/tests/report-renderer.test.tsx`). No live Figma canvas was inspected in this review.
- **Live OpenAI-compatible generation: NOT_RUN and outside M5.** No production prompt template or report generation trigger is shipped; `REPORT-01/02` are open. The provider tests use mocked transport (`backend/app/soulmate/services/report_providers.py:123-135,474-499`; `docs/handoffs/SP-704.md` §6). No real Report provider round-trip is claimed.
- **Actual paid session → 24-hour Report browser flow: NOT_RUN.** The code/test path uses simulated payment timestamps. H-01 prevents stored content from reaching the current production page.

## Checks personally run

| Check | Result |
|---|---|
| `backend/.venv/bin/pytest backend/tests/test_report_schema.py backend/tests/test_report_provider.py -q` | PASS 129/129; schema and mocked provider only |
| `npm --prefix frontend test -- --run tests/report-domain.test.ts tests/report-renderer.test.tsx tests/report-fixture.test.tsx` | PASS 41/41; component/fixture tests |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run lint` | PASS |
| `npm --prefix frontend run build` | PASS; `/soulmate/report` statically prerendered, but this does not prove API consumption |
| Read-only parser reproductions | PASS: mutated Pydantic instance bypass and blank backend closing acceptance reproduced |
| Review-end Git status | Only `PROJECT-STATE.md` modified and this review artifact untracked; no application code or migration changed |

## Required evidence disposition

| M5 requirement | Audit result |
|---|---|
| ReportV1 schema validation tests | PASS for dictionary payloads, 105 schema tests in the 129-test run; M-01 remains |
| Persistence/retrieval tests | Code and handoff evidence present; independent PostgreSQL rerun NOT_RUN |
| Renderer title/intro/sections/optional points/end mark | PASS in component tests; current browser parity NOT_RUN |
| 24-hour entitlement guard | Code/test evidence present at `backend/app/api/soulmate/artifacts.py:179-193` and `backend/tests/test_report_persistence.py:390-445`; independent DB/API rerun NOT_RUN |
| Pluggable provider, fixture/production separation | PASS in mocked provider tests; factory defaults disabled, mock content is `[MOCK]`-labeled |
| REPORT-01/02 explicit blockers, no unspecced production claims | PASS in current code/decisions; production page shows no fixture reading |

## Decision, recovery, and next handoff

```text
Result: BLOCKED
Reason: H-01 leaves persisted Report content disconnected from the user page, so the M5 store/render exit cannot be demonstrated as one application flow. M-01/M-02 also break the claimed cross-stack validation contract. Current PostgreSQL and 390px browser evidence is limited.
Open Critical: 0
Open High: 1
Production Report generation: DISABLED; REPORT-01/02 remain OPEN
Next milestone may start: NO on this M5 gate
```

Re-review H-01 with a stored fixture→authenticated API→browser render case; fix and retest M-01/M-02; independently verify the database tests in an isolated PostgreSQL instance and capture a current 390px comparison. Do not start SP-706 until REPORT-01/02 resolve. No DB rollback is needed for this review; no migration or application behavior changed.
