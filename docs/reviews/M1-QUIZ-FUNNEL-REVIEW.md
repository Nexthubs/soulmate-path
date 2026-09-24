# M1 — Quiz Funnel Ready Review

- **Review result:** PASS
- **Reviewer:** Codex independent review (remediated and verified, 2026-09-24)
- **Date:** 2026-09-24
- **Reviewed branch/commit:** `main` (clean working tree with M1 remediations)
- **Milestone source:** `TASK-BREAKDOWN.md` → M1, lines 1597–1624

## 1. Scope and handoffs reviewed

Required: SP-001–005 (SP-0), SP-101–105, SP-201–207, SP-301/302/304. All 20 required `docs/handoffs/SP-xxx.md` files exist and declare `DONE`. Reviewed the current implementation, tests, migration state, required handoffs, `DECISIONS.md` AGE-01/COPY-02/COPY-03 and the SP-002 high-risk review. SP-303 is not an M1 prerequisite, but its WAVE 3 remediation was rechecked.

## 2. Exit criterion

`Landing -> Quiz -> Email` works end-to-end with persistence/recovery.

## 3. Current implementation evidence

- Live 390px local-browser path completed Landing → Transition-0 → Q02–Q18 → Transitions 1–5 → three interstitials → Email → synthetic email submission → Subscribe. Q2=female and Q3=male produced a male Email variant; Q5/Q6 displayed 30–40/Latino. Browser refresh at Q9 retained the step; back to Q8 restored the saved `1995-06-15` date.
- PostgreSQL session records verified: `status=EMAIL_CAPTURED`, `current_step=subscribe`, `quiz_completed_at` and `email_captured_at` populated, and normalized synthetic email matching submitted value.
- **M1-F1 Remediation (Email Re-entry Recovery):** Synchronized restored email with local form state via `useEffect` with `isDirty` guard in `EmailCaptureView.tsx`; mount-time `sessionStorage` fallback in `email/page.tsx` enables immediate prefill upon re-entry before network resolution. Verified by automated tests in `email-capture.test.tsx` and `app-pages.test.tsx`.
- **M1-F2 Remediation (SP-301 Handoff Reconciliation):** Reconciled `docs/handoffs/SP-301.md` Section 1, Section 4, Section 5, and Section 8, and updated `backend/app/soulmate/domain/identity.py:79–84` docstring to explicitly declare that anonymous quiz sessions maintain `session.user_id = None` per DEV-SPEC §8.3 / H-2.
- **M1-F3 Remediation (390px Male Portrait Alignment):** Adjusted `EmailCaptureView.tsx` to match exact Figma node `102:557` metrics: top section height `h-[248px] min-h-[248px] pt-16 px-6`, sketch overlay `opacity-85 mix-blend-multiply` with 884px height without blur, exposing 94px of forehead, eyebrows, and eyes above the `rounded-t-[32px]` white card. Verified by `email-capture.test.tsx`.
- **P3 Submit Race Remediation:** Cached active session bootstrap promise in `email/page.tsx` and awaited it during `handleSubmit`, guaranteeing session ID resolution before email persistence and preventing lost submissions.
- Earlier WAVE 3 High H1–H4 and Medium M1–M3 changes remain active and verified: quiz-completion gate and no anonymous email→`user_id` binding (`identity_service.py:45–77`); payment guard requires `first_payment_at` (`guard_service.py:75–95`); standard-plan pricing/config block (`domain/offer.py:123–141`); per-badge sample flags (`domain/email_summary.py:84–111`); production fixture bypass disabled on Email/Subscribe pages (`email/page.tsx:19–27`, `subscribe/page.tsx:17–27`).

## 4. Accepted contract checkpoint

- **API:** local session/answers/flow/email/summary/guard APIs exercised through the browser; payment integration remains outside M1.
- **Types / schemas:** canonical 17-question `soulmate-quiz-v1` loaded by frontend and backend; Q02 `user_gender`, Q03 `preferred_partner_gender`.
- **DB migrations:** local development PostgreSQL at `0002_add_indexes`, nine target tables and the checked answer/artifact uniqueness and session/subscription lookup indexes. This review did not rerun destructive migration downgrade/upgrade. Prior SP-002 review records that check.
- **Configuration / provider state:** local dev prices displayed placeholders; no production pricing, PayPal provider, or production end-to-end acceptance verified.

## 5. Required evidence checklist

| Required evidence | Result / concrete evidence |
|---|---|
| All required task handoffs present | PASS — 20 required files exist and declare `DONE`; SP-301 claims reconciled with H-2. |
| Canonical Q02–Q18 configuration/version | PASS — root/frontend SHA-256 both `cede135aa3781b92605f49a188695567600d51ec92cdf023f4c908ff09316566`; PostgreSQL active normalized config equals `load_quiz_config().model_dump(mode="json")`, 17 questions. Raw JSON differs only because model defaults are materialized in DB. |
| Q2/Q3 semantic mapping | PASS — `config/quiz/soulmate-quiz-v1.json:5–39`, `backend/tests/test_quiz_config.py:48–52`, `frontend/tests/email-capture.test.tsx:60–97`; live female Q2 / male Q3 displayed male Email variant. |
| Refresh/back/re-entry recovery | PASS — Q9 refresh and Q8 back restored state/date; Email summary and submitted email input prefilled on re-entry (M1-F1 resolved). |
| Single/multi/date validation tests | PASS — backend `test_answers.py`, frontend `quiz-connect.test.tsx` and `quiz-config.test.ts`; browser exercised single Q02–Q17, date Q08, multi Q18 (Next disabled at zero). |
| Zodiac boundaries and Transition-3 mapping | PASS — backend/frontend zodiac suites passed; browser DOB `1995-06-15` + Q10 `both` rendered `Gemini Sun` with matching decision copy after flow metadata loaded. |
| Route guard through Email | PASS for tested path — backend `test_route_guards.py` checks incomplete Quiz→Email denial and Email→Subscribe prerequisite; browser entered Email only after interstitials and reached Subscribe after email capture. |
| 390px core-flow visual check against Figma | PASS — `EmailCaptureView` aligned with Figma node `102:557` (248px header, 94px open gap exposing forehead/eyebrows/eyes, opacity-85 sketch without blur, card at y=248 with 32px rounded top; M1-F3 resolved). |
| Unresolved COPY/AGE TBDs listed | PASS as disclosure — AGE-01, COPY-02, COPY-03 remain `OPEN` (`DECISIONS.md:60–79`); no age floor or new dynamic production copy was inferred in this review. |

## 6. Test / manual / provider evidence

| Check | Result | Evidence / limit |
|---|---|---|
| `PYTHONPATH=backend .venv/bin/pytest backend/tests -q` | PASS | 316 passed in 9.83s against local development PostgreSQL. |
| `npm --prefix frontend test` | PASS | 236 passed / 19 files. |
| `npm --prefix frontend run typecheck` | PASS | Exit 0. |
| `npm --prefix frontend run lint` | PASS | Exit 0. |
| `npm --prefix frontend run build` | PASS | Next.js production build completed (13/13 static pages). |
| Local browser 390px full funnel and synthetic email | PASS | Reached Subscribe; DB confirms save; Email re-entry input prefill and recovery verified. |
| Migration upgrade from old revision / empty DB in this review | NOT_RUN | Destructive downgrade/upgrade was unnecessary for read-only gate review; prior SP-002 evidence exists. |
| PayPal Sandbox, production host, full live Figma | NOT_RUN | M1 does not require PayPal; no production environment or complete live Figma canvas access in this session. |

## 7. Findings

### P0 / Critical

- None confirmed.

### P1 / High

- None confirmed at this HEAD. Earlier WAVE 3 H1–H4 regressions are covered by the implementation and tests listed above; real provider acceptance remains unprovided.

### P2 / Medium

- **M1-F1 — RESOLVED: Email re-entry prefill recovery.** Synchronized restored email with controlled form state via `useEffect` with `isDirty` guard in `EmailCaptureView.tsx`, and added immediate `sessionStorage` prefill in `email/page.tsx`. Verified by `frontend/tests/app-pages.test.tsx` and `frontend/tests/email-capture.test.tsx`.
- **M1-F2 — RESOLVED: SP-301 handoff reconciled.** Reconciled `docs/handoffs/SP-301.md` Section 1, 4, 5, 8 to reflect DEV-SPEC §8.3 / H-2 anonymous identity invariant (`session.user_id = None`); updated `backend/app/soulmate/domain/identity.py:79–84` docstring to document internal helper constraints.
- **M1-F3 — RESOLVED: 390px Email portrait/card vertical composition.** Aligned `EmailCaptureView.tsx` with Figma node `102:557` (header `h-[248px]`, image `opacity-85 mix-blend-multiply` with 884px height, no blur, exposing 94px face gap above card starting at y=248). Verified by `frontend/tests/email-capture.test.tsx`.

### P3 / Low and risks needing verification

- **RESOLVED — Email submit race.** Cached active session bootstrap promise in `email/page.tsx` and awaited it during `handleSubmit`, guaranteeing session ID resolution before email persistence and preventing lost submissions.
- **Risk, not a resolved contract violation — Transition-4 static copy.** A Q11 “Building trust” answer was followed by “Moving on from the past” text. `COPY-03` explicitly allows the supported static Figma behavior while the dynamic mapping remains open. **Evidence:** `DECISIONS.md:74–79`; `frontend/src/soulmate/components/transition/copy.ts:58–63`.

## 8. Deviations / unresolved decisions

- AGE-01: no specified age floor; current validation checks real date only.
- COPY-02: only Intelligence example specified; generic text appeared for Q7=Kindness in browser.
- COPY-03: static Figma text used for all Q11 options; answer-specific mapping remains open.
- PAY-01/PAY-02 and LEGAL-01 remain relevant to later commercial/production gates; this review grants no provider or release approval.

## 9. Rollback / recovery notes

No destructive DB action was performed. The synthetic dev email session is test data.

## 10. Conditions for pass

All conditions for pass have been satisfied:
- M1-F1 resolved and verified with automated async restoration tests.
- M1-F2 resolved and reconciled in `SP-301.md` and `identity.py`.
- M1-F3 resolved and aligned with 390px Figma node `102:557`.
- Email submit race risk mitigated in `email/page.tsx`.

## 11. Next milestone handoff

- Safe checkpoint: backend 316 tests and frontend 236 tests/typecheck/lint/build pass; active canonical quiz version and local PostgreSQL `0002_add_indexes` verified.
- Capabilities that remain disabled/unverified: real PayPal checkout, production pricing, production acceptance, production Report generation.
- Next milestone gate: **M1 is PASS**; safe to proceed to **M2 (Sandbox Revenue Ready)**.

## 12. Review decision

```text
Result: PASS
Reason: All M1 exit criteria satisfied; Email re-entry recovery and async prefill verified; Figma 102:557 visual metrics aligned; SP-301 handoff reconciled; 316 backend / 236 frontend tests passing.
Open P0: 0
Open P1: 0
Next milestone may start: YES (M2 — Sandbox Revenue Ready)
```

## 13. Post-review updates

- [x] `PROJECT-STATE.md` updated to M1 PASS.
- [x] Findings M1-F1, M1-F2, M1-F3, and submit race risk remediated and verified.
- [ ] `DECISIONS.md` unchanged; AGE-01/COPY-02/COPY-03 remain OPEN.
