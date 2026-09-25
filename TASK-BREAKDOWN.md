# TASK-BREAKDOWN.md — Soulmate Path V1.2

> Executable scope/dependency/acceptance plan derived from `Soulmate-Path-DEV-SPEC-v1.2.md`.
> Model assignment is intentionally not part of this file.

## 0. How to use this file

For an assigned Task, load **this Task block only** first, then follow its context metadata:

- **Priority** — delivery/security importance.
- **Depends** — direct prerequisite Task IDs/interfaces.
- **Status** — `TODO | IN_PROGRESS | BLOCKED | REVIEW | DONE`.
- **Context refs** — exact DEV-SPEC sections and decision entries needed for the task.
- **Acceptance / Tests** — completion contract.

Context rule:

```text
AGENTS.md + PROJECT-STATE.md
        ↓
assigned Task block
        ↓
Spec refs + Decision refs + direct dependency handoffs only
```

Do not read the full DEV-SPEC, all decisions, all handoffs, or all reviews unless this task is explicitly cross-cutting/release review.

Task evidence/handoff format is owned by `AGENTS.md`; this file does not repeat it.

## 1. Global dependency map

```text
SP-0 Foundation
  ├── SP-1 UI Shell (fixture-driven) ─────────────┐
  └── SP-2 Quiz Backend ──> SP-3 Email ──> SP-4 PayPal
                                             │
                                             v
                                        SP-5 Result
                                          /      \
                                         v        v
                                     SP-6 Sketch SP-7 Report scaffold
                                          \       /
                                           v     v
                                          SP-8 Account
                                             │
                                             v
                                          SP-9 Ops
                                             │
                                             v
                                         SP-10 QA
```

### Critical path

```text
SP-001/002/003
-> SP-201/202/203
-> SP-301/304
-> SP-401..408
-> SP-501..505
-> SP-601..607
-> SP-1002..1006
```

### Safe parallel work

After interfaces are stable:

- `SP-1` UI can proceed against fixtures while `SP-2` backend is built.
- `SP-703` report renderer can proceed while production report generation remains blocked.
- `SP-901` analytics definitions can proceed alongside core implementation.
- `SP-801/802` drawer routing can proceed after Result status contract is stable.

---

# WAVE 0 — Repository discovery and contracts

## SP-001 — Soulmate module / route namespace

**Priority:** P1  
**Depends:** none  
**Status:** DONE
**Context refs:** DEV-SPEC §3, §16–17, §22 | Decisions: DOMAIN-01 | Dependency handoffs: —


### Goal
Create the minimal Soulmate feature boundary without imposing a new framework or folder convention.

### Work
- Inspect existing route/module conventions.
- Create `/soulmate` route namespace or repository-equivalent.
- Add feature-level domain/service/component directories only where consistent with the repo.
- Wire feature flags if the repository uses them.
- Add a minimal smoke route/page/handler proving the module is reachable.

### Acceptance
- Existing app behavior is unchanged outside Soulmate.
- `/soulmate` can be reached in development.
- No unnecessary new framework/runtime dependency.
- Route ownership is clear enough for later Quiz/Email/Result pages.

### Tests
- route smoke test or framework equivalent;
- existing build/typecheck.

---

## SP-002 — Database migration foundation

**Priority:** P0  
**Depends:** repository discovery  
**Status:** DONE
**Context refs:** DEV-SPEC §14, §15, §20 | Decisions: PAY-AUTH-01, TIME-01, ASSET-01 | Dependency handoffs: docs/handoffs/SP-001.md


### Goal
Create the V1 persistence model using the repository's existing DB conventions.

### Work
Implement or adapt the spec's entities for:
- quiz versions/config;
- soulmate sessions;
- answers/interstitial answers;
- subscription/provider references;
- payment ledger;
- webhook events;
- artifacts/generation jobs;
- reports.

Prefer existing generic user/subscription/payment/job tables where available.

### Required constraints
- one answer per `session_id + question_code`;
- unique provider webhook event ID;
- stable unique PayPal subscription/payment IDs where applicable;
- DB-enforced sketch uniqueness at the strongest stable identity available;
- timestamps in UTC;
- no provider secrets stored.

### Acceptance
- clean migration applies on empty/dev DB;
- rollback behavior follows repo policy;
- schema supports all APIs in spec §15;
- indexes exist for normal lookups by session/user/email/provider IDs.

### Tests
- migration apply test;
- uniqueness constraint tests where supported.

### Review
Mandatory high-risk review before merge.

---

## SP-003 — Canonical `soulmate-quiz-v1` config

**Priority:** P1  
**Depends:** SP-001, preferably SP-002  
**Status:** DONE
**Context refs:** DEV-SPEC §4.1–4.6 | Decisions: QUIZ-01 | Dependency handoffs: SP-001, SP-002, SP-003


### Goal
Turn the approved Q02–Q18 configuration into an immutable, reviewable runtime artifact.

### Work
- Add canonical JSON/config matching spec §4.6.
- Validate question codes, order, types, result keys, option codes, and required flags.
- Add import/seed path compatible with the repo.
- Session creation must pin `quiz_version = soulmate-quiz-v1`.

### Acceptance
- exactly Q02–Q18 are present;
- Q18 is the only multi-select question;
- Q08 is date;
- Q02/Q03 result keys remain distinct;
- invalid duplicate question/option codes fail validation.

### Tests
- config schema validation;
- snapshot/fixture test if used by repo.

---

## SP-004 — Environment and secrets

**Priority:** P0  
**Depends:** SP-001  
**Status:** DONE
**Context refs:** DEV-SPEC §22 | Decisions: DOMAIN-01, PAY-01 | Dependency handoffs: SP-001, SP-004


### Goal
Define config surface without hard-coded production values.

### Required config groups
- app/base URL;
- PayPal environment/client credentials/product-plan IDs/prices or pricing config;
- OpenAI API/model config;
- storage bucket/CDN config;
- report provider feature flag/config;
- job/worker config if applicable.

### Acceptance
- `.env.example` or repo-equivalent documents all required keys;
- real secrets are ignored/not committed;
- application fails clearly on missing mandatory production config;
- `INTRO_PRICE` and `REGULAR_PRICE` are not scattered literals.

---

## SP-005 — Error codes / request correlation

**Priority:** P1  
**Depends:** SP-001  
**Status:** DONE
**Context refs:** DEV-SPEC §19 | Decisions: — | Dependency handoffs: SP-001


### Goal
Establish consistent errors before API surface grows.

### Work
- Reuse existing request ID/correlation mechanism or add the repo-standard equivalent.
- Define Soulmate domain errors for validation, invalid flow state, payment pending, locked asset, generation failed, forbidden ownership, provider unavailable.
- Map internal/provider errors to safe user-facing responses.

### Acceptance
- provider raw errors/secrets never reach clients;
- logs include correlation/request IDs;
- API errors are machine-readable enough for frontend states.

---

# WAVE 1 — Fixture-driven UI shell

## SP-101 — Landing page

**Priority:** P1  
**Depends:** SP-001  
**Status:** DONE
**Context refs:** DEV-SPEC §1–3, §21 | Decisions: LEGAL-01, DOMAIN-01 | Dependency handoffs: SP-001


### Figma
`102:44`

### Work
- Implement responsive landing page using existing design system.
- CTA -> Transition-0/session start behavior via fixture initially.
- Login button -> existing login flow.
- Replace temporary Figma MCP asset URLs with stable project assets.

### Acceptance
- 390px design baseline visually matches Figma;
- wider viewport remains usable;
- CTA/login keyboard accessible;
- no unverified production claims are introduced.

---

## SP-102 — Shared Quiz layout

**Priority:** P1  
**Depends:** SP-101  
**Status:** DONE
**Context refs:** DEV-SPEC §2.1, §4.2–4.4, §16 | Decisions: QUIZ-01 | Dependency handoffs: SP-101


### Figma
`102:121`, `102:201`

### Work
Create shared shell for:
- back navigation;
- question title/subtitle;
- options/input area;
- bottom action region where needed;
- loading/error state.

### Acceptance
- no per-question page duplication;
- Q08 date, single-select, and Q18 multi-select can all render in the shell;
- Back is supported.

---

## SP-103 — `OptionCard` variants

**Priority:** P1  
**Depends:** SP-102  
**Status:** DONE
**Context refs:** DEV-SPEC §2.1, §4.2–4.3 | Decisions: — | Dependency handoffs: SP-102


### Work
Implement reusable unselected/selected/disabled/focus/error-compatible option card.

### Acceptance
- selected visual matches Figma;
- single and multi behaviors use the same visual primitive;
- accessible label/input semantics;
- touch target remains usable on mobile.

---

## SP-104 — Transition shared layout + interstitial shells

**Priority:** P1  
**Depends:** SP-101  
**Status:** DONE
**Context refs:** DEV-SPEC §5 | Decisions: COPY-02, COPY-03 | Dependency handoffs: SP-101


### Figma
`102:245`, `102:304`, `102:320`, `102:345`, `102:372`, `102:386`, `102:425`, `102:466`, `102:445`

### Work
- Transition page shell for steps 0–5.
- Progress/visual states used by Transition-5.
- Generic yes/no interstitial modal.
- Warning modal.
- Dynamic-copy slots without inventing missing product copy.

### Acceptance
- confirmed static/dynamic text can be injected as data;
- `COPY-02`/`COPY-03` remain explicit fallbacks/TBDs, not guessed copy;
- modal focus/escape behavior follows app accessibility patterns.

---

## SP-105 — Email male/female variants

**Priority:** P1  
**Depends:** SP-102  
**Status:** DONE
**Context refs:** DEV-SPEC §2, §8 | Decisions: QUIZ-01 | Dependency handoffs: SP-102


### Figma
`102:486`, `102:557`

### Work
Single page component driven by `preferred_partner_gender`.

Render summary from:
- Q3 soulmate gender;
- Q5 age range;
- Q6 ethnicity.

### Acceptance
- not implemented as two independent business pages;
- email validation/error/submitting states exist;
- correct visual variant chosen by Q3, not Q2.

---

## SP-106 — Result cards fixture UI

**Priority:** P1  
**Depends:** SP-101  
**Status:** DONE
**Context refs:** DEV-SPEC §2, §10 | Decisions: TIME-01 | Dependency handoffs: SP-101


### Figma
`102:1201`, `102:1332`

### Work
Create fixture-driven cards for:
- locked/countdown;
- ready;
- generating;
- completed;
- failed/retryable display.

### Acceptance
- same card API can consume the future Result aggregate API;
- countdown presentation does not itself grant access.

---

## SP-107 — Sketch viewer fixture UI

**Priority:** P1  
**Depends:** SP-101  
**Status:** DONE
**Context refs:** DEV-SPEC §2, §11 | Decisions: ASSET-01, PROMPT-01 | Dependency handoffs: SP-101


### Figma
`102:461`

### Acceptance
- loading/completed/failed states;
- completed image uses durable URL prop;
- Back destination is configurable from app route config, not hard-coded domain string.

---

## SP-108 — Report renderer fixture UI

**Priority:** P1  
**Depends:** SP-101  
**Status:** DONE
**Context refs:** DEV-SPEC §2, §13, §16 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-101


### Figma
`102:1358`

### Work
Render `ReportV1` structured JSON only; do not render arbitrary AI Markdown/HTML.

### Acceptance
- title/intro/sections/optional points supported;
- long content wraps safely;
- fixture visually matches Figma editorial layout;
- no production AI dependency.

---

# WAVE 2 — Quiz backend and frontend integration

## SP-201 — Session create / recover

**Priority:** P1  
**Depends:** SP-002, SP-003  
**Status:** DONE
**Context refs:** DEV-SPEC §6, §15.1 | Decisions: — | Dependency handoffs: SP-002, SP-003


### Work
- create anonymous Soulmate session;
- persist `quiz_version`;
- recover by authorized session cookie/token mechanism matching repo conventions;
- expose current step/status and saved answers needed to restore UI.

### Acceptance
- refresh resumes current step;
- old session remains bound to original quiz version;
- no arbitrary session ID allows cross-user/session access.

### Tests
- create;
- recover;
- invalid/expired ownership;
- version pinning.

---

## SP-202 — Answer upsert and validation

**Priority:** P1  
**Depends:** SP-201, SP-003  
**Status:** DONE
**Context refs:** DEV-SPEC §4, §15.3 | Decisions: QUIZ-01 | Dependency handoffs: SP-201, SP-003


### Work
- validate question exists in session version;
- validate type-specific payload;
- validate option membership;
- upsert one answer per question;
- Q18 deduplicate values;
- Q08 validate date.

### Acceptance
- duplicate rapid single taps cannot create duplicate rows;
- invalid option codes are rejected;
- saved answer can be edited by Back/re-answer flow according to current spec.

---

## SP-203 — Flow / next-step resolver

**Priority:** P0  
**Depends:** SP-202  
**Status:** DONE
**Context refs:** DEV-SPEC §4–6 | Decisions: QUIZ-01, COPY-02, COPY-03 | Dependency handoffs: SP-202



### Goal
Centralize the authoritative state machine for Questions, Transitions, Interstitials, Email.

### Acceptance
- no frontend-maintained independent step list is required for correctness;
- sequence matches spec §1.1 and §5;
- resolver is deterministic and unit-tested;
- invalid skips are rejected/redirected by API/guards.

### Tests
Table-driven coverage of every edge in Q02–Q18 and Transition-0–5.

---

## SP-204 — DOB / Zodiac

**Priority:** P1  
**Depends:** SP-202  
**Status:** DONE  
**Context refs:** DEV-SPEC §4.4, §5.5 | Decisions: AGE-01 | Dependency handoffs: SP-202


### Acceptance
- server computes zodiac using product-defined boundaries;
- all boundary dates have tests;
- client may display returned zodiac but is not authoritative;
- `AGE-01` is not invented.

---

## SP-205 — Normalized Soulmate Profile builder

**Priority:** P1  
**Depends:** SP-202, SP-204  
**Status:** DONE  
**Context refs:** DEV-SPEC §7 | Decisions: QUIZ-01 | Dependency handoffs: SP-202, SP-204


### Goal
Map raw versioned answers into the normalized profile consumed by Email summary, Sketch, Report.

### Required fields
At minimum preserve the mappings defined in spec §7, including:
- user gender;
- preferred partner gender/age/ethnicity;
- key quality;
- birth date/zodiac;
- element;
- decision style;
- relationship preferences/fears/goals.

### Acceptance
- pure/testable mapping;
- unknown/missing required answers surface explicit validation error;
- no Q2/Q3 ambiguity.

---

## SP-206 — Interstitial answer storage

**Priority:** P2  
**Depends:** SP-203  
**Status:** DONE
**Context refs:** DEV-SPEC §5.7, §15.4 | Decisions: — | Dependency handoffs: SP-203


### Work
Store answers for spiritual/Psychic Artistry/warning interstitial flow as defined in spec, without mixing them into Q02–Q18 identifiers.

### Acceptance
- idempotent update;
- analytics can reference the interstitial answer without PII.

---

## SP-207 — Connect Quiz UI to live APIs

**Priority:** P1  
**Depends:** SP-102/103/104, SP-201/202/203  
**Status:** DONE  
**Context refs:** DEV-SPEC §4–6, §15–16 | Decisions: QUIZ-01, COPY-02, COPY-03, AGE-01 | Dependency handoffs: SP-102, SP-201


### Work
- session bootstrap;
- render current server step;
- single-select auto-submit/advance;
- multi-select explicit submit;
- date submit;
- Back/recovery;
- network error/retry.

### Acceptance
- fixture mode is removable/isolated;
- refresh at any question restores answer/state;
- rapid taps are locked while request is in flight;
- server resolver remains authoritative.

---

# WAVE 3 — Email and conversion boundary

## SP-301 — Email save / normalize / bind identity

**Priority:** P0  
**Depends:** SP-201, SP-205  
**Status:** DONE
**Context refs:** DEV-SPEC §8, §15.5, §20 | Decisions: — | Dependency handoffs: SP-201, SP-205


### Work
- validate and normalize email;
- bind anonymous session to existing/new user identity using existing account model;
- preserve session ownership;
- define duplicate/existing-email behavior using repo conventions.

### Acceptance
- normalized identity is consistent for later one-email-one-sketch logic;
- user cannot bind another user's session by ID;
- no password/auth system is invented if existing product uses another mechanism.

---

## SP-302 — Email summary API/view model

**Priority:** P1  
**Depends:** SP-205  
**Status:** DONE
**Context refs:** DEV-SPEC §8 | Decisions: QUIZ-01 | Dependency handoffs: SP-205


### Acceptance
Returns display-ready Q3/Q5/Q6 values or equivalent normalized profile fields, without frontend guessing labels from raw codes.

---

## SP-303 — Subscribe offer/config API

**Priority:** P1  
**Depends:** SP-301, SP-004  
**Status:** DONE
**Context refs:** DEV-SPEC §9.1–9.2, §15.6, §21–22 | Decisions: PAY-01, PAY-02 | Dependency handoffs: SP-301, SP-004


### Goal
Expose the current offer safely to UI.

### Response should support
- currency;
- intro price;
- regular monthly price;
- renewal disclosure;
- eligibility/plan class if policy is resolved;
- PayPal client integration metadata that is safe for browser use.

### Acceptance
- UI does not hard-code price;
- `PAY-01` can be configured without source changes;
- `PAY-02` remains configurable/blocked rather than guessed.

---

## SP-304 — Route guards

**Priority:** P0  
**Depends:** SP-203, SP-301  
**Status:** DONE
**Context refs:** DEV-SPEC §3, §10, §20 | Decisions: PAY-AUTH-01, TIME-01 | Dependency handoffs: SP-203, SP-301


### Acceptance
Matches spec §3 for Quiz/Email/Subscribe/Result/Sketch/Report, with server-side authorization as final authority.

---

# WAVE 4 — PayPal monthly subscription

## SP-401 — PayPal Product/Plan provisioning

**Priority:** P0  
**Depends:** SP-004  
**Status:** DONE
**Context refs:** DEV-SPEC §9.1–9.2, §22, §25 | Decisions: PAY-01, PAY-02 | Dependency handoffs: SP-004


### Goal
Provision reusable PayPal billing objects for monthly subscription.

### Required structure
- intro plan: paid first-month promotional billing phase, then recurring regular monthly phase;
- standard plan if required by `PAY-02` policy;
- no per-user plan creation.

### Deliverables
- repeatable provisioning script or documented one-time command through repo tooling;
- config output for Product ID / Plan ID(s);
- Sandbox plan verification.

### Acceptance
- prices come from config/approved input;
- plan cadence is monthly;
- renewal disclosure values match plan;
- safe to re-run or clearly detects existing provisioned plan.

### Review
Mandatory high-risk review.

---

## SP-402 — PayPal JS subscription checkout

**Priority:** P0  
**Depends:** SP-303, SP-401, SP-105 or subscription page UI  
**Status:** DONE (docs/handoffs/SP-402.md)
**Context refs:** DEV-SPEC §9.3, §15.6, §21 | Decisions: PAY-01, PAY-02, PAY-AUTH-01 | Dependency handoffs: SP-303, SP-401, SP-105


### Work
- render PayPal subscription action in existing frontend framework;
- request correct plan from server offer/config;
- create/approve subscription;
- route to payment-processing state after approval;
- never set entitlement from client callback.

### Acceptance
- success callback does not mark user paid;
- cancel/error states return to recoverable UI;
- amount/renewal disclosure matches server offer.

---

## SP-403 — Confirm subscription API

**Priority:** P0  
**Depends:** SP-402  
**Status:** DONE (docs/handoffs/SP-403.md)
**Context refs:** DEV-SPEC §9.3–9.4, §15.7 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-402


### Goal
Associate approved provider subscription with the authorized user/session and expose pending/confirmed state.

### Acceptance
- provider subscription ID validated server-side;
- ownership/session binding enforced;
- duplicate confirmation is idempotent;
- entitlement remains pending until successful payment event/reconciliation.

---

## SP-404 — PayPal webhook endpoint with raw body

**Priority:** P0  
**Depends:** SP-002, SP-004  
**Status:** DONE (docs/handoffs/SP-404.md)
**Context refs:** DEV-SPEC §9.5–9.6 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-002, SP-004


### Acceptance
- raw request data required for provider verification is preserved according to framework;
- endpoint is not protected by normal user auth;
- unverified events never mutate business state;
- response behavior supports PayPal retry semantics.

---

## SP-405 — Webhook signature verification

**Priority:** P0  
**Depends:** SP-404  
**Status:** DONE
**Context refs:** DEV-SPEC §9.6 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-404


### Acceptance
- official verification mechanism is used;
- verification failure is logged safely and rejected;
- tests include forged/invalid signature path.

---

## SP-406 — Event idempotency and out-of-order handling

**Priority:** P0  
**Depends:** SP-405  
**Status:** DONE
**Context refs:** DEV-SPEC §9.5–9.6, §14 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-405


### Work
- persist provider event ID before/with processing transaction;
- duplicate event returns success without duplicate business effects;
- state transition logic tolerates events arriving out of order;
- reconciliation path exists for ambiguous state.

### Acceptance
- replay same successful payment event N times -> one ledger entry/one entitlement activation;
- cancellation/activation/payment events cannot regress state incorrectly because of stale event order.

---

## SP-407 — Payment ledger

**Priority:** P0  
**Depends:** SP-406  
**Status:** DONE
**Context refs:** DEV-SPEC §9.4–9.7, §14 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-406


### Acceptance
- each completed provider payment has durable provider payment ID, amount, currency, paid time, subscription link, cycle context when available;
- duplicate provider payment ID cannot create multiple rows;
- support lookup for customer support/reconciliation.

---

## SP-408 — Subscription reconciliation/state mapping

**Priority:** P0  
**Depends:** SP-403, SP-406, SP-407  
**Status:** TODO
**Context refs:** DEV-SPEC §9.4–9.8, §10 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-403, SP-406, SP-407


### Goal
Map provider state into application subscription/entitlement state without trusting only one webhook.

### Acceptance
- first successful payment sets authoritative `first_payment_completed_at` exactly once;
- next billing/status can be reconciled from provider when needed;
- failure/suspension/cancel/expire states map predictably;
- already-owned generated artifacts are not deleted on cancellation.

---

## SP-409 — Cancellation and Settings action

**Priority:** P1  
**Depends:** SP-408, SP-803  
**Status:** TODO
**Context refs:** DEV-SPEC §9.8, §15.9 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-408, SP-803


### Acceptance
- cancellation uses server-side provider API;
- current paid-through/access semantics shown correctly;
- repeated cancel is safe/idempotent;
- cancelled users retain previously generated artifacts.

---

## SP-410 — Payment-processing frontend state

**Priority:** P1  
**Depends:** SP-403, SP-408  
**Status:** TODO
**Context refs:** DEV-SPEC §9.3–9.4 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-403, SP-408


### Acceptance
- after PayPal approval, UI polls/refetches server state;
- only transitions to Result after confirmed first payment;
- timeout/pending case is recoverable and does not falsely claim success.

---

# WAVE 5 — Result / countdown / artifact entitlement

## SP-501 — Artifact entitlement rows on first payment

**Priority:** P0  
**Depends:** SP-408, SP-002  
**Status:** TODO
**Context refs:** DEV-SPEC §9.4, §10, §14 | Decisions: PAY-AUTH-01, TIME-01 | Dependency handoffs: SP-408, SP-002


### Work
On first successful payment, transactionally create/ensure:
- Sketch entitlement/artifact placeholder;
- Report entitlement/report placeholder;
- unlock timestamps based on authoritative payment time.

### Acceptance
- duplicate payment/webhook does not duplicate rows;
- `sketch_unlock_at = first_payment_completed_at + 12h`;
- `report_unlock_at = first_payment_completed_at + 24h`.

---

## SP-502 — 12h/24h status derivation

**Priority:** P0  
**Depends:** SP-501  
**Status:** TODO
**Context refs:** DEV-SPEC §10 | Decisions: TIME-01 | Dependency handoffs: SP-501


### Acceptance
- derived from server time + persisted timestamps;
- client clock changes do not grant access;
- `LOCKED`, `READY`, `GENERATING`, `COMPLETED`, `FAILED` are distinguishable;
- unit tests use injectable/fake clock.

---

## SP-503 — Result aggregate API

**Priority:** P1  
**Depends:** SP-502  
**Status:** TODO
**Context refs:** DEV-SPEC §10.4, §15.8 | Decisions: TIME-01 | Dependency handoffs: SP-502


### Goal
Single API supplies Result page with subscription + sketch + report status and server time.

### Acceptance
- no need for client to merge 4–5 independent authority calls;
- response contains only authorized user's data;
- stable schema supports SP-106 and polling.

---

## SP-504 — Frontend countdown using server time

**Priority:** P1  
**Depends:** SP-503, SP-106  
**Status:** TODO
**Context refs:** DEV-SPEC §10.4, §16 | Decisions: TIME-01 | Dependency handoffs: SP-503, SP-106


### Acceptance
- countdown uses server-time offset or returned remaining time;
- refresh recalibrates from server;
- reaching zero triggers status refetch rather than locally granting content.

---

## SP-505 — Result polling/refetch strategy

**Priority:** P1  
**Depends:** SP-503  
**Status:** TODO
**Context refs:** DEV-SPEC §10.4 | Decisions: TIME-01 | Dependency handoffs: SP-503


### Acceptance
- bounded/appropriate polling while payment/generation pending;
- polling stops on terminal state/unmount;
- backoff or repo-standard query behavior prevents request storms.

---

# WAVE 6 — Soulmate Sketch generation

## SP-601 — Versioned Sketch prompt template

**Priority:** P1  
**Depends:** SP-205  
**Status:** TODO
**Context refs:** DEV-SPEC §11.2–11.3, §12 | Decisions: PROMPT-01 | Dependency handoffs: SP-205


### Goal
Implement the PRD-provided prompt as a versioned template with explicit inputs.

### Inputs
- `preferred_partner_gender` -> `gender`;
- `preferred_partner_age_range` -> `age_range`;
- `preferred_partner_ethnicity` -> `ethnicity`;
- `key_soulmate_quality` -> `features` (V1 compatibility mapping).

### Acceptance
- prompt version stored with generated asset;
- no missing placeholder can reach provider;
- mapping is covered by tests;
- `PROMPT-01` is not silently changed.

---

## SP-602 — OpenAI image provider adapter

**Priority:** P1  
**Depends:** SP-004, SP-601  
**Status:** TODO
**Context refs:** DEV-SPEC §11–12, §22, §25 | Decisions: PROMPT-01, ASSET-01 | Dependency handoffs: SP-004, SP-601


### Acceptance
- provider call is isolated behind app-owned interface;
- configured model defaults to spec target `gpt-image-2`;
- browser never sees API key;
- provider error categories map to domain errors;
- request metadata useful for tracing is recorded safely.

---

## SP-603 — Generation queue / worker

**Priority:** P0  
**Depends:** SP-501, SP-602  
**Status:** TODO
**Context refs:** DEV-SPEC §11.4, §11.6 | Decisions: ASSET-01 | Dependency handoffs: SP-501, SP-602


### Work
Use existing job system if present. If not, implement the smallest repo-consistent async mechanism.

### Acceptance
- generation can survive request lifecycle;
- job state is durable enough for retry/observability;
- concurrent enqueue attempts converge on one logical generation.

---

## SP-604 — Retry / idempotency

**Priority:** P0  
**Depends:** SP-603  
**Status:** TODO
**Context refs:** DEV-SPEC §11.4–11.6, §19 | Decisions: ASSET-01 | Dependency handoffs: SP-603


### Acceptance
- transient failures retry with bounded attempts/backoff;
- permanent invalid/safety/input failures do not loop forever;
- a retry never creates a second owned sketch after a success;
- attempt count/final category stored.

### Concurrency test
20 concurrent triggers for the same eligible identity must produce one logical asset/generation winner.

---

## SP-605 — Durable object storage

**Priority:** P0  
**Depends:** SP-602/603  
**Status:** TODO
**Context refs:** DEV-SPEC §11.7 | Decisions: ASSET-01 | Dependency handoffs: SP-602


### Acceptance
- successful provider output is copied to project-owned storage;
- stable storage key/URL metadata persisted;
- MIME/type/size validated according to existing storage rules;
- temporary provider URL is not the durable source of truth.

---

## SP-606 — One-email-one-sketch constraint

**Priority:** P0  
**Depends:** SP-301, SP-604, SP-002  
**Status:** TODO
**Context refs:** DEV-SPEC §11.5, §14 | Decisions: ASSET-01 | Dependency handoffs: SP-301, SP-604, SP-002


### Goal
Enforce the PRD rule at DB/domain level, not only UI.

### Acceptance
- normalized email/linked user identity is used consistently;
- second eligible session for same identity returns existing sketch rather than generating a new one;
- race condition covered by DB constraint/transaction.

### Note
If existing account semantics make user-ID uniqueness safer than email uniqueness, preserve the PRD's user-facing “one email” behavior while documenting the canonical DB key and reconciliation rule.

---

## SP-607 — Live Sketch page states

**Priority:** P1  
**Depends:** SP-107, SP-503, SP-605, SP-606  
**Status:** TODO
**Context refs:** DEV-SPEC §2, §10–11 | Decisions: ASSET-01, TIME-01 | Dependency handoffs: SP-107, SP-503, SP-605, SP-606


### Acceptance
- locked users route to Result;
- ready/generating display correct state;
- completed displays persisted asset;
- refresh never triggers regeneration;
- failed state follows retry policy without enabling duplicate generation.

---

# WAVE 7 — Soulmate Report scaffold

## SP-701 — `ReportV1` schema

**Priority:** P1  
**Depends:** SP-205  
**Status:** TODO
**Context refs:** DEV-SPEC §13.2 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-205


### Acceptance
Schema supports Figma structure:
- title;
- intro;
- ordered sections;
- section title/body;
- optional points/action items;
- schema/version field.

Validation rejects arbitrary executable HTML/script content.

---

## SP-702 — Report persistence

**Priority:** P1  
**Depends:** SP-701, SP-501  
**Status:** TODO
**Context refs:** DEV-SPEC §13.2, §14, §15.11 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-701, SP-501


### Acceptance
- report JSON/version/status persisted;
- authorized retrieval only;
- one canonical current V1 report per entitled identity/session according to domain model.

---

## SP-703 — Report renderer parity

**Priority:** P1  
**Depends:** SP-108, SP-701  
**Status:** TODO
**Context refs:** DEV-SPEC §2, §13, §16 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-108, SP-701


### Figma
`102:1358`

### Acceptance
- renderer consumes only validated `ReportV1`;
- long text/optional points render safely;
- 390px parity acceptable;
- no arbitrary Markdown/HTML injection.

---

## SP-704 — Report generation provider interface

**Priority:** P1  
**Depends:** SP-701  
**Status:** TODO
**Context refs:** DEV-SPEC §13.3–13.4 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-701


### Goal
Create a provider interface without choosing unspecced production content.

### Acceptance
- input uses normalized profile/versioned context;
- output must validate against `ReportV1`;
- provider implementation can be mock/disabled;
- production switch is off until `REPORT-01/02` close.

---

## SP-705 — Report mock fixture

**Priority:** P2  
**Depends:** SP-701  
**Status:** TODO
**Context refs:** DEV-SPEC §13.2–13.3 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-701


### Acceptance
- fixture is clearly non-production/test content;
- supports renderer and E2E testing;
- does not pretend to be an actual personalized reading.

---

## SP-706 — Production Report generator

**Priority:** P1  
**Depends:** SP-704 + `REPORT-01` + `REPORT-02`  
**Status:** BLOCKED
**Context refs:** DEV-SPEC §13.3–13.4 | Decisions: REPORT-01, REPORT-02 | Dependency handoffs: SP-704


### Do not start until
Product explicitly provides/approves model/rules, prompt, output constraints, and any safety/compliance requirements.

---

# WAVE 8 — Drawer / Settings / account integration

## SP-801 — Drawer Soulmate entry

**Priority:** P1  
**Depends:** SP-001  
**Status:** TODO
**Context refs:** DEV-SPEC §2–3 | Decisions: DOMAIN-01 | Dependency handoffs: SP-001


### Figma
`102:14`

### Acceptance
Adds `Soulmate Sketch` entry without duplicating global navigation infrastructure.

---

## SP-802 — Status-aware Drawer destination

**Priority:** P1  
**Depends:** SP-503, SP-801  
**Status:** TODO
**Context refs:** DEV-SPEC §3, §10 | Decisions: PAY-AUTH-01, TIME-01 | Dependency handoffs: SP-503, SP-801


### Routing
```text
no successful first payment -> /soulmate
paid, sketch locked -> /soulmate/result
unlocked/generating -> /soulmate/result or /soulmate/sketch per final UX contract
completed -> /soulmate/sketch
```

### Acceptance
Destination comes from server-authoritative status, not local membership flag only.

---

## SP-803 — Subscription details in Settings

**Priority:** P1  
**Depends:** SP-408  
**Status:** TODO
**Context refs:** DEV-SPEC §2, §9.8 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-408


### Figma
`102:1423`, `102:1460`

### Acceptance
Shows current plan/status/regular monthly price/next billing or paid-through information using provider-reconciled backend state.

---

## SP-804 — Cancel action UI

**Priority:** P1  
**Depends:** SP-409, SP-803  
**Status:** TODO
**Context refs:** DEV-SPEC §9.8, §15.9 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-409, SP-803


### Acceptance
- confirmation state;
- safe repeated action;
- clear post-cancel access message;
- no deletion of completed sketch/report.

---

## SP-805 — Paid-through access display

**Priority:** P1  
**Depends:** SP-408, SP-803  
**Status:** TODO
**Context refs:** DEV-SPEC §9.8, §10 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-408, SP-803


### Acceptance
Copy is derived from actual access date/state and does not promise an unsupported refund/renewal behavior.

---

# WAVE 9 — Analytics and operations

## SP-901 — Funnel event contract and instrumentation

**Priority:** P1  
**Depends:** stable UI/API flows  
**Status:** TODO
**Context refs:** DEV-SPEC §18 | Decisions: — | Dependency handoffs: —


### Minimum events
- `soulmate_landing_view`
- `soulmate_start_click`
- `quiz_started`
- `quiz_question_view`
- `quiz_answered`
- `quiz_back`
- `quiz_completed`
- `email_page_view`
- `email_submitted`
- `subscribe_page_view`
- `checkout_click`
- `payment_started`
- `payment_success`
- `payment_failed`
- `result_view`
- `sketch_unlocked`
- `sketch_viewed`
- `sketch_generated`
- `sketch_generation_failed`
- `report_unlocked`
- `report_viewed`

### Acceptance
- events use central analytics wrapper;
- event schema documented;
- no raw email/DOB/full answers in analytics properties unless explicitly approved.

---

## SP-902 — Generation metrics

**Priority:** P1  
**Depends:** SP-603/604  
**Status:** TODO
**Context refs:** DEV-SPEC §18–19 | Decisions: ASSET-01 | Dependency handoffs: SP-603


### Metrics
- queue latency;
- generation latency;
- success/failure/retry counts;
- final failure rate;
- duplicate/idempotency conflict count if useful.

---

## SP-903 — Payment / webhook metrics

**Priority:** P0  
**Depends:** SP-406/408  
**Status:** TODO
**Context refs:** DEV-SPEC §18–19 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-406


### Metrics
- webhook verification failures;
- event processing failures;
- duplicate event count;
- first-payment confirmation latency;
- reconciliation mismatch count;
- payment failures by safe reason category.

---

## SP-904 — Alerts

**Priority:** P0  
**Depends:** SP-902/903, existing monitoring  
**Status:** TODO
**Context refs:** DEV-SPEC §19 | Decisions: — | Dependency handoffs: SP-902


### Alert candidates
- sustained PayPal webhook processing failure;
- signature verification anomaly spike;
- generation final-failure spike;
- worker queue stuck/backlog threshold;
- storage write failures;
- provider outage pattern.

Use existing alerting platform; do not create a second monitoring stack.

---

## SP-905 — Admin/support lookup

**Priority:** P1  
**Depends:** core DB + payment + artifact tables  
**Status:** TODO
**Context refs:** DEV-SPEC §14, §19–20 | Decisions: PAY-AUTH-01, ASSET-01 | Dependency handoffs: —


### Goal
Allow authorized support to trace a case by safe identifiers.

### Lookup keys
- session ID;
- normalized/hashed or appropriately protected email per existing admin policy;
- PayPal subscription ID;
- provider payment ID.

### Acceptance
Shows timeline/status without exposing provider secrets or unrelated users' data.

---

# WAVE 10 — QA, hardening, release

## SP-1001 — Mobile/browser matrix

**Priority:** P1  
**Depends:** core UI complete  
**Status:** TODO
**Context refs:** DEV-SPEC §2, §23 | Decisions: — | Dependency handoffs: —


### Minimum
Use the product's supported browser policy; at least validate representative iOS Safari, Android Chrome, desktop Chrome/Safari if supported.

### Acceptance
No blocking layout/input/payment UI defects at 390px baseline and supported widths.

---

## SP-1002 — PayPal Sandbox full-flow test

**Priority:** P0  
**Depends:** SP-401..410, SP-501..503  
**Status:** TODO
**Context refs:** DEV-SPEC §9, §23, §25 | Decisions: PAY-01, PAY-02, PAY-AUTH-01 | Dependency handoffs: SP-401, SP-501


### Scenario
Landing/eligible user -> Subscribe -> PayPal approval -> webhook/payment confirmation -> Result.

### Acceptance
- first payment ledger exists exactly once;
- first payment timestamp drives unlocks;
- UI does not show success before server confirmation;
- subscription status is queryable/reconcilable.

---

## SP-1003 — Webhook replay and out-of-order test

**Priority:** P0  
**Depends:** SP-406/408  
**Status:** TODO
**Context refs:** DEV-SPEC §9.5–9.6, §23 | Decisions: PAY-AUTH-01 | Dependency handoffs: SP-406


### Cases
- identical event replay 2x/10x;
- payment event before/after activation event;
- cancellation after success;
- stale activation after cancellation;
- transient handler failure then retry.

### Acceptance
No duplicate entitlements/payments and no invalid state regression.

---

## SP-1004 — Concurrency test

**Priority:** P0  
**Depends:** SP-604/606  
**Status:** TODO
**Context refs:** DEV-SPEC §11.4–11.6, §23 | Decisions: ASSET-01 | Dependency handoffs: SP-604


### Cases
- parallel answer upserts;
- parallel payment event processing;
- parallel sketch generation triggers.

### Acceptance
DB invariants hold; exactly one owned sketch is created for one eligible identity.

---

## SP-1005 — Security / IDOR test

**Priority:** P0  
**Depends:** all user APIs  
**Status:** TODO
**Context refs:** DEV-SPEC §20, §23 | Decisions: PAY-AUTH-01, TIME-01 | Dependency handoffs: —


### Cases
- access another session by ID;
- access another sketch/report;
- spoof paid/unlocked fields from browser;
- call generate before unlock;
- invalid webhook/signature;
- manipulate route only without entitlement.

### Acceptance
All unauthorized paths denied without leaking target existence/content more than platform norms allow.

---

## SP-1006 — Production smoke and release checklist

**Priority:** P0  
**Depends:** all release tasks + required TBD closure  
**Status:** TODO
**Context refs:** DEV-SPEC §21–23, §26 | Decisions: PAY-01, PAY-02, DOMAIN-01, LEGAL-01, REPORT-01, REPORT-02 | Dependency handoffs: —


### Preconditions
Close all release-blocking product items:
- `PAY-01`;
- applicable `PAY-02` behavior;
- `AGE-01` if legally/product-required;
- copy TBDs used in production;
- `DOMAIN-01`;
- `LEGAL-01`;
- `REPORT-01/02` only if production AI report generation is enabled.

### Smoke
- production config validates;
- correct PayPal production plan IDs/prices;
- webhook endpoint verified;
- start -> quiz -> email path;
- controlled real/production-like payment test according to release policy;
- result access;
- sketch generation/storage/retrieval;
- settings/cancel path;
- analytics/alerts receiving expected events.

### Acceptance
All P0/P1 test cases pass and rollback/disable strategy is documented.

---

# 11. Cross-cutting review tasks

These are not replacements for implementation tasks; they are explicit quality gates.

## RV-01 — Schema + state-machine review

**After:** SP-203, SP-408, SP-502  
**Status:** TODO
**Context refs:** DEV-SPEC §6, §9–15, §20 | Decisions: QUIZ-01, PAY-AUTH-01, TIME-01, ASSET-01 | Dependency handoffs: —


Review:
- state transition completeness;
- impossible/ambiguous states;
- DB invariants;
- retry/idempotency boundaries;
- timestamp authority.

---

## RV-02 — Payment security review

**After:** SP-401..409  
**Status:** TODO
**Context refs:** DEV-SPEC §9–10, §20, §23 | Decisions: PAY-01, PAY-02, PAY-AUTH-01, TIME-01 | Dependency handoffs: —


Review:
- plan selection;
- client trust boundary;
- signature verification;
- duplicate/out-of-order webhooks;
- reconciliation;
- cancellation;
- ledger correctness.

---

## RV-03 — Sketch generation correctness review

**After:** SP-601..607  
**Status:** TODO
**Context refs:** DEV-SPEC §11–12, §14, §20, §23 | Decisions: PROMPT-01, ASSET-01, TIME-01 | Dependency handoffs: —


Review:
- Q3/Q5/Q6/Q7 mapping;
- prompt versioning;
- unique generation;
- retry behavior;
- storage durability;
- authorization.

---

## RV-04 — Release compliance/content review

**Before:** SP-1006  
**Status:** TODO
**Context refs:** DEV-SPEC §18, §20–23, §26 | Decisions: LEGAL-01, DOMAIN-01, REPORT-01, REPORT-02, PAY-01, PAY-02 | Dependency handoffs: —


Verify:
- no fake testimonials/statistics;
- subscription disclosure matches actual plan;
- unresolved copy/report TBDs are not exposed as invented production content;
- privacy/analytics fields are appropriate.

---

# 11A. Task evidence

Task handoff requirements are defined only in `AGENTS.md §7`. Every Task reaching `REVIEW`/`DONE` must produce `docs/handoffs/<TASK-ID>.md`; do not duplicate the generic handoff schema here.

---

# 12. Milestones and review gates

A milestone is a **review gate**, not a synonym for "all tasks appear finished". Required tasks must first reach `DONE` with durable handoffs. Then the named reviewer inspects the implementation and produces the required review artifact.

Allowed milestone states:

```text
NOT_STARTED -> IN_PROGRESS -> REVIEW -> PASS
                              ├-------> CONDITIONAL_PASS
                              └-------> BLOCKED
```

`CONDITIONAL_PASS` is allowed only when the remaining condition is explicitly documented, does not conceal an open P0/P1 correctness/security issue, and does not make the next milestone unsafe.

## M1 — Quiz Funnel Ready

**Required:**
- SP-0 complete;
- SP-101..105;
- SP-201..207;
- SP-301/302/304.

**Exit criterion:**  
`Landing -> Quiz -> Email` works end-to-end with persistence/recovery.

**Required review artifact:**
```text
docs/reviews/M1-QUIZ-FUNNEL-REVIEW.md
```

**Review owner:** independent reviewer; should not be the primary implementer of the majority of the milestone when avoidable.

**Required evidence:**
- all required task handoffs present;
- canonical Q02–Q18 configuration/version verified;
- Q2/Q3 semantic mapping verified;
- refresh/back/re-entry recovery evidence;
- single/multi/date validation tests;
- zodiac boundary tests and Transition-3 mapping tests;
- route-guard evidence through Email;
- 390px core flow visual check against Figma;
- unresolved COPY/AGE TBDs explicitly listed without guessed production behavior.

## M2 — Sandbox Revenue Ready

**Required:**
- SP-303;
- SP-401..410;
- RV-02 review scope complete.

**Exit criterion:**  
PayPal Sandbox completes the discounted first monthly payment and backend confirms it correctly.

**Required review artifact:**
```text
docs/reviews/M2-PAYPAL-SANDBOX-REVIEW.md
```

**Review owner:** independent high-risk reviewer with payment/webhook/entitlement expertise.

**Required evidence:**
- PayPal Product/Plan configuration/provisioning evidence with no hard-coded production secrets;
- intro-month -> regular-month billing cycle verified in Sandbox/config;
- client approval alone does not grant entitlement;
- webhook signature verification test/evidence;
- duplicate webhook replay evidence;
- out-of-order/provider reconciliation scenario evidence;
- payment ledger and unique provider event IDs verified;
- first successful payment timestamp recorded as entitlement source;
- cancellation/settings path verified to the extent supported by Sandbox;
- exact unresolved PAY-01/PAY-02 production blockers listed.

## M3 — Entitlement / Result Ready

**Required:**
- SP-501..505.

**Exit criterion:**  
12h/24h logic is server-authoritative and all result UI states are testable with a fake/test clock.

**Required review artifact:**
```text
docs/reviews/M3-ENTITLEMENT-RESULT-REVIEW.md
```

**Review owner:** independent reviewer; entitlement logic requires high-risk correctness review.

**Required evidence:**
- payment -> artifact entitlement creation evidence;
- `sketch_unlock_at = first_payment_completed_at + 12h` tests;
- `report_unlock_at = first_payment_completed_at + 24h` tests;
- client clock tampering cannot unlock content;
- LOCKED/READY/GENERATING/COMPLETED/FAILED state coverage where applicable;
- route authorization/ownership checks;
- test-clock scenario matrix;
- Result aggregate API contract checkpoint recorded.

## M4 — Sketch Ready

**Required:**
- SP-601..607;
- RV-03.

**Exit criterion:**  
A paid eligible user receives exactly one durable generated sketch, including retry/recovery paths.

**Required review artifact:**
```text
docs/reviews/M4-SKETCH-REVIEW.md
```

**Review owner:** independent high-risk reviewer for uniqueness/concurrency/idempotency; add visual/provider review as needed.

**Required evidence:**
- prompt input mapping Q3/Q5/Q6/Q7 verified;
- prompt/model version metadata persisted;
- provider failure and bounded retry evidence;
- concurrent generation trigger produces one durable asset;
- one-email/identity uniqueness constraint demonstrated at DB/domain boundary;
- successful result copied into project-owned object storage;
- revisiting Sketch retrieves same durable asset;
- loading/completed/failed UI evidence;
- no temporary provider URL used as permanent asset source.

## M5 — Report Scaffold Ready

**Required:**
- SP-701..705.

**Exit criterion:**  
Report can be stored/rendered from validated structured fixture data. Production generation may remain off.

**Required review artifact:**
```text
docs/reviews/M5-REPORT-SCAFFOLD-REVIEW.md
```

**Review owner:** independent reviewer with schema/provider-boundary competence.

**Required evidence:**
- `ReportV1` schema validation tests;
- persistence/retrieval tests;
- renderer covers title/intro/sections/optional points/end mark;
- 24h entitlement guard verified;
- provider interface is pluggable;
- fixture and production provider are clearly separated;
- `REPORT-01/02` remain explicit production blockers unless `DECISIONS.md` resolves them;
- no unspecced production soulmate/psychological claims are generated.

## M6 — Production Ready

**Required:**
- SP-8;
- SP-9;
- SP-10;
- relevant production-blocking TBDs closed in `DECISIONS.md`;
- RV-01..04 complete;
- prior milestone review conditions closed or explicitly accepted.

**Exit criterion:**  
The production configuration, security, observability, payment, entitlement, generated assets, and core mobile funnel satisfy the V1 Definition of Done.

**Required review artifact:**
```text
docs/reviews/M6-PRODUCTION-READINESS-REVIEW.md
```

**Review owner:** independent release reviewer plus QA evidence; product approval is required for unresolved product/legal copy decisions.

**Required evidence:**
- full E2E happy path in production-like environment;
- PayPal production plan IDs/prices checked against approved decision/config without exposing secrets;
- webhook replay/out-of-order suite;
- concurrency suite;
- authorization/IDOR suite;
- production smoke test;
- analytics funnel event check;
- alerting/operational lookup check;
- mobile browser matrix;
- database migration/recovery/rollback notes;
- no P0/P1 open findings unless explicitly waived by named owner;
- fake testimonials/unverified statistics absent from production;
- `PROJECT-STATE.md` updated to production-ready/released state.

### Milestone review protocol

For every milestone:

1. Implementers finish required tasks and write `docs/handoffs/SP-xxx.md`.
2. Milestone moves to `REVIEW`, not directly to `PASS`.
3. Reviewer reads the current code/diffs, handoffs, test output, migrations/config, and executes/repeats critical checks as appropriate.
4. Reviewer creates the named `docs/reviews/Mx-*.md` from `docs/templates/MILESTONE-REVIEW-TEMPLATE.md`.
5. Reviewer records `PASS`, `CONDITIONAL_PASS`, or `BLOCKED`.
6. Reviewer updates `PROJECT-STATE.md` with the accepted milestone state and next safe Task IDs.
7. Any newly resolved cross-task decision is recorded in `DECISIONS.md`; major architecture choices use an ADR.

---


# 13. Completion protocol

Generic task completion/handoff rules are owned by `AGENTS.md §7–9`. Task-specific completion is determined by each Task's `Acceptance` / `Tests` plus its required handoff artifact.

---

# 14. Recommended first task sequence

For a new repository/branch, start narrowly and expand after contracts stabilize:

```text
1. SP-001 — repository architecture inventory / feature boundary
2. SP-002 — schema review + migration foundation
3. SP-003 — canonical quiz config
4. SP-101..104 — fixture UI shell may proceed once the feature boundary is stable
5. SP-201..203 — session + answer + flow resolver
6. SP-207 — live Quiz integration
7. SP-301 — email identity binding
8. SP-401..408 — PayPal foundation
9. SP-501..505 — Result / entitlement state machine
10. SP-601..606 — Sketch backend
11. SP-607 — Sketch UI integration
12. SP-701..705 — Report scaffold
13. SP-8 / SP-9 / SP-10 — account, ops, hardening, release
```

This sequence proves identity, payment, and state-machine correctness before production AI/release work.

---

**End of `TASK-BREAKDOWN.md` — v1.2**