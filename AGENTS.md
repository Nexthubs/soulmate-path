# AGENTS.md — Soulmate Path

> Repository-level execution contract for agents working on **Soulmate Path**.
> Keep this file at the repository root (or at the nearest common parent of the Soulmate feature).
> If a deeper directory contains its own `AGENTS.md`, the deeper file may add narrower rules but must not weaken payment, privacy, idempotency, or source-of-truth requirements in this file.

## 1. Read this before changing code

For every Soulmate task, read in this order:

1. `AGENTS.md` — execution rules and guardrails.
2. `Soulmate-Path-DEV-SPEC-v1.md` — product/technical source of truth.
3. `TASK-BREAKDOWN.md` — task scope, dependency, acceptance criteria, and recommended execution lane.
4. Existing repository conventions — framework, routing, DB/migration style, auth, payments, jobs, storage, analytics, tests.
5. Figma source only when the task changes a user-visible screen or component.

Do not start implementation from a task title alone.

## 2. Source-of-truth hierarchy

Use the hierarchy defined in the development spec:

- **Business rules**: PRD / `Soulmate-Path-DEV-SPEC-v1.md`.
- **Quiz wording, answer meaning, question numbering**: `灵魂伴侣问题&选项.xlsx` as normalized into `soulmate-quiz-v1`.
- **User-visible layout and visual states**: Figma Soulmate Path.
- **Third-party API semantics**: current official PayPal/OpenAI API behavior, adapted through project-owned provider interfaces.
- **Repository implementation style**: the existing codebase.

If two sources conflict and the development spec already records the conflict, follow the recorded decision/TBD. If the conflict is new, stop that narrow part of the task and report it; do not invent a product decision.

## 3. Non-negotiable product semantics

The following meanings must never drift:

- `q02 -> user_gender` = the user's own gender.
- `q03 -> preferred_partner_gender` = the requested soulmate gender and the person shown in the sketch.
- `q05 -> preferred_partner_age_range`.
- `q06 -> preferred_partner_ethnicity`.
- `q07 -> key_soulmate_quality`; V1 passes this value into the sketch prompt's `features` slot only because the current PRD requires it. Do not reinterpret the question.
- `q08 -> birth_date`; zodiac is calculated on the server.
- `q10 -> decision_style`; it drives Transition-3 copy.
- `q18` is multi-select; all other configured choice questions are single-select.
- Quiz version is immutable per session: `soulmate-quiz-v1`.

Do not rename these result keys casually. They are API/data contracts.

## 4. Known TBDs are blockers, not invitations to improvise

Do not silently resolve these items:

- `PAY-01`: concrete first-month promotional price.
- `PAY-02`: whether re-subscribers can receive the introductory price again.
- `AGE-01`: DOB/minimum-age rule.
- `COPY-02`: Transition-2 copy variants beyond the confirmed example.
- `COPY-03`: Transition-4 dynamic-copy rules.
- `REPORT-01`: production report generation model/rules.
- `REPORT-02`: production report prompt/content specification.
- `PROMPT-01`: whether Q7 remains mapped to sketch `features` long term.
- `DOMAIN-01`: canonical production domain.
- `LEGAL-01`: final truthful testimonials/statistics.

A task may build infrastructure around a TBD if the interface is already specified. Production behavior that requires the unresolved decision must remain feature-gated, configured, mocked, or blocked as stated in `TASK-BREAKDOWN.md`.

## 5. First action for every implementation task: inspect the repo

Before coding, identify and reuse:

- framework and language;
- route conventions;
- auth/session/user identity model;
- DB ORM/query layer and migration style;
- configuration/secrets system;
- existing payment/provider abstractions;
- background job/queue infrastructure;
- object storage wrapper;
- component library/design tokens;
- analytics abstraction;
- logging/error monitoring;
- test stack and fixtures.

Do **not** introduce React, Tailwind, Prisma, FastAPI, BullMQ, Redis, S3 SDK wrappers, analytics SDKs, or any other major dependency merely because an example in the spec resembles that technology.

Prefer the repository's existing primitive unless it cannot satisfy the requirement. If a new dependency is genuinely required, explain why before adding it.

## 6. Scope discipline

Implement the assigned Task ID(s), their direct prerequisites, and the minimum integration needed to make them correct.

Do not:

- refactor unrelated modules for style;
- rename existing public APIs without need;
- change quiz wording outside a product-approved copy task;
- modify payment prices or PayPal plan IDs in source code;
- turn mock/fake testimonials into production claims;
- implement production report content from model imagination;
- regenerate a completed sketch because a page is revisited;
- rely on browser time for unlock authorization;
- treat a client callback as proof of payment.

If a task exposes a pre-existing bug that blocks correct implementation, fix the smallest safe surface and record it in the handoff.

## 7. Multi-agent / multi-model working agreement

This project may be implemented by multiple Codex models. Treat Task IDs and contracts as the coordination layer.

### 7.1 Recommended routing convention

This is a project dispatch convention, not a hard requirement. If model names or capabilities change, route by **task risk/complexity**, not by label.

| Task class | Recommended lane | Typical work |
|---|---|---|
| Architecture / high-risk correctness | **Astra** | schema design review, PayPal state/reconciliation, idempotency, auth/IDOR, concurrency, release review, cross-module refactor |
| Complex end-to-end implementation | **Sol** | session/flow engine, payment integration, result aggregation, worker/provider integration, complex Figma page integration |
| Bounded feature implementation | **Terra** | CRUD endpoints, UI components, route guards, settings integration, analytics wiring, integration tests |
| Small/localized work | **Luna** | fixtures, copy-safe UI states, simple unit tests, config plumbing, documentation, low-risk cleanup |

Rules:

- Payment, entitlement, concurrency, authorization, and migration tasks should receive a **high-risk review** even if initially implemented in a lighter lane.
- A lighter model may implement a well-specified bounded task; do not let it redefine architecture to make the task easier.
- Reviews must inspect actual diffs/tests, not merely restate the spec.

### 7.2 Parallel work rules

Parallelize only tasks with non-overlapping ownership or stable interfaces.

Good parallelization examples:

- UI fixture implementation vs. DB/session foundation.
- PayPal provider adapter vs. Result UI against fixtures.
- Report renderer vs. report generator interface.
- Analytics event definitions vs. visual QA.

Avoid parallel edits to the same high-churn files, especially:

- central route registries;
- shared API schema/type files;
- the same DB migration;
- the same payment webhook handler;
- the same Quiz flow resolver.

When parallel work is unavoidable, agree the shared interface first and keep one agent responsible for integration.

## 8. Task execution protocol

### Before coding

1. Locate the Task ID in `TASK-BREAKDOWN.md`.
2. Read its dependencies and blockers.
3. Verify prerequisite code actually exists; do not assume another agent completed it.
4. Inspect the relevant existing modules.
5. State internally the exact acceptance criteria to be satisfied.

### While coding

- Keep business rules in domain/service code, not scattered across views.
- Use typed/stable API schemas when the stack supports them.
- Make externally-triggered writes idempotent.
- Make state transitions explicit and auditable.
- Use UTC timestamps in persistence/API contracts; localize only for display.
- Use transactions around multi-table financial/entitlement changes when supported.
- Prefer deterministic pure functions for zodiac, flow resolution, status derivation, and prompt input mapping.
- Preserve provider payload/event IDs for debugging without exposing secrets.

### Before finishing

1. Run the narrowest relevant tests, then broader tests if affordable.
2. Run lint/typecheck/build commands required by the repo.
3. Re-check acceptance criteria.
4. Re-check authorization, idempotency, retry behavior, and failure states where relevant.
5. Do not mark a task complete if tests are skipped without explicitly saying why.

## 9. Mandatory handoff format

Every completed task should end with a concise handoff containing:

```text
Task: SP-xxx
Status: DONE | PARTIAL | BLOCKED

Changed:
- <important files/modules>

Implemented:
- <behavior>

Tests:
- <commands and result>

Decisions:
- <only implementation decisions that do not change product semantics>

Blockers / follow-ups:
- <TBD or known issue>
```

Do not report `DONE` when a required migration, test, provider verification, or acceptance criterion remains incomplete.

## 10. Database and migration rules

- Follow existing migration tooling and naming.
- Prefer additive migrations in active development; avoid destructive schema rewrites unless explicitly approved.
- Financial/provider IDs that require uniqueness must have DB-level constraints where practical.
- Enforce one answer per `session_id + question_code`.
- Enforce webhook event idempotency by provider event ID.
- Enforce sketch uniqueness at the strongest stable identity available per the spec; do not rely only on an in-memory check.
- Store provider state separately from derived application entitlement state when needed for reconciliation.
- Never store PayPal or OpenAI secrets in DB rows or logs.

If the repo already has generic user/subscription/payment tables, extend/reuse them rather than duplicating Soulmate-specific versions unless the domain model requires separation.

## 11. Quiz engine rules

The UI is data-driven. Do not create one component/page per question.

Required behavior:

- single choice: save then auto-advance;
- multi choice: selection first, explicit Next;
- date: validated date submission;
- Back restores prior selection;
- refresh/return restores server-side session state;
- old sessions continue using the quiz version captured at creation;
- unrecognized question/option values are rejected server-side;
- server is authoritative for current/next step.

Keep flow resolution testable without a browser.

## 12. Figma implementation rules

For user-visible Figma tasks:

- Use the Figma design as visual reference and existing repo design tokens/components as implementation primitives.
- Do not paste generated React/Tailwind from Figma MCP verbatim unless it already matches the repository stack and conventions.
- Reuse shared `OptionCard`, quiz layout, transition shell, result card, typography, spacing, and button primitives.
- Do not commit temporary Figma MCP asset URLs; export/host stable assets through the project's normal asset path.
- Verify at the 390px mobile design baseline and at least one wider responsive viewport.
- Implement loading, disabled, selected, error, and completed states—not only the screenshot's happy state.

## 13. PayPal rules — high risk

PayPal is monthly subscription billing with:

- first billing month at promotional `INTRO_PRICE`;
- subsequent months at `REGULAR_PRICE`;
- recurring until cancelled/expired according to configured plan behavior.

Rules:

- Product/Plan IDs and prices are config/provider data, never literals embedded in UI business logic.
- Prefer provisioned PayPal Product/Plan objects; do not create a new plan per user.
- The first successful payment, not merely client `onApprove`, activates Soulmate entitlement.
- Use server-side/webhook-confirmed payment state.
- Verify webhook authenticity using the project's correct raw-body/signature flow.
- Store and deduplicate PayPal event IDs.
- Webhook handlers must tolerate retry and out-of-order delivery.
- Maintain a payment ledger sufficient for support/reconciliation.
- Cancellation must not delete already generated/owned artifacts.
- Route/UI state must be derived from server subscription + entitlement state.

Any change touching webhook handling, entitlement creation, reconciliation, or cancellation needs tests for duplicate events and failure/retry behavior.

## 14. Result and entitlement rules

Use server timestamps as authority.

```text
sketch_unlock_at = first_payment_completed_at + 12h
report_unlock_at = first_payment_completed_at + 24h
```

The browser may render a countdown from server-provided time, but cannot authorize access.

Support explicit states such as:

```text
LOCKED -> READY -> GENERATING -> COMPLETED
                         \-> FAILED
```

Do not conflate `unlocked` with `generated`.

## 15. Sketch generation rules — high risk

Canonical V1 prompt inputs:

```text
Q3 -> gender
Q5 -> age_range
Q6 -> ethnicity
Q7 -> features (temporary PRD mapping)
```

Rules:

- Model/provider calls happen on the server/worker, never directly from the browser.
- Use the configured image model; current spec target is `gpt-image-2`.
- Prompt is versioned (`soulmate_sketch_v1` or repository-equivalent).
- Generation is asynchronous when repository infrastructure supports jobs.
- Job creation and generation are idempotent.
- Retry transient provider failures with bounded attempts/backoff.
- Persist successful output in project-owned object storage; do not depend on a temporary provider URL.
- Revisiting `/soulmate/sketch` returns the persisted asset, not a new generation.
- Record generation model, prompt version, provider request ID if available, attempt count, and final error category.

Do not change demographic constraints or prompt semantics under the guise of “quality improvement” without a product task.

## 16. Report rules

V1 must support:

- `ReportV1` structured JSON schema;
- persistence;
- 24h entitlement guard;
- renderer matching Figma;
- pluggable generation interface;
- mock/fixture content for development/tests.

Production AI generation is blocked by `REPORT-01` / `REPORT-02` until those are explicitly closed. Do not generate and ship unspecced soulmate/psychological claims.

## 17. Analytics rules

Use the repository analytics abstraction. Do not call vendor SDKs directly from feature components if a wrapper exists.

Minimum funnel must allow reconstruction of:

```text
Landing view
-> Start
-> Quiz started
-> Quiz completed
-> Email submitted
-> Subscribe viewed
-> Checkout started
-> First payment succeeded
-> Result viewed
-> Sketch unlocked/viewed/completed
-> Report unlocked/viewed
```

Avoid sending raw email, DOB, full answer payloads, provider secrets, or AI prompts as analytics properties unless an approved analytics schema explicitly requires and permits them.

## 18. Security and privacy checklist

For every relevant endpoint:

- derive user/session ownership server-side;
- prevent IDOR by arbitrary session/user IDs;
- validate inputs against quiz/config schema;
- do not trust client-supplied payment status, entitlement status, unlock times, or user IDs;
- protect webhook endpoints with provider verification, not app-user auth;
- protect user endpoints with the repo's normal auth/session mechanism;
- avoid sensitive PII in logs;
- normalize email consistently before identity/uniqueness logic;
- apply rate limiting/abuse controls through existing platform primitives where appropriate.

## 19. Testing expectations

Use the repo's native test framework. At minimum, cover the surfaces relevant to the task.

### Unit

- zodiac boundaries;
- Quiz answer validation;
- next-step resolver;
- profile mapping;
- subscription/result status derivation;
- prompt input mapping;
- retry/idempotency helpers.

### Integration

- session create/recover;
- answer upsert;
- email binding;
- PayPal webhook signature + duplicate event handling;
- payment -> entitlement/artifact creation;
- cancellation/reconciliation;
- sketch job -> storage -> retrieval;
- report persistence/retrieval.

### E2E

- Landing -> Quiz -> Email;
- PayPal Sandbox checkout -> confirmed Result;
- 12h/24h state transitions with controllable test clock;
- refresh/back/recovery;
- duplicate webhook/replay;
- concurrent sketch trigger produces one durable asset;
- unauthorized cross-user access denied.

Do not weaken assertions merely to make flaky tests pass. Fix the source of nondeterminism when possible.

## 20. Review severity

Treat findings in these areas as release-blocking unless explicitly waived:

**P0**
- payment can be spoofed;
- entitlement can be obtained without successful payment;
- webhook forgery accepted;
- cross-user sketch/report exposure;
- duplicate charging caused by our integration logic;
- destructive data loss of paid artifacts.

**P1**
- duplicate sketch generation despite idempotency requirement;
- wrong Q2/Q3 gender mapping;
- 12h/24h bypass using client clock;
- wrong recurring price/plan displayed or selected;
- session answers lost on refresh;
- production fake testimonial/statistic shipped.

**P2**
- non-blocking visual mismatch;
- analytics gaps;
- recoverable copy/spacing defects.

## 21. Standard task prompt

For consistent execution across Agents, tasks may be launched with this template:

```text
Implement Task <SP-ID> from TASK-BREAKDOWN.md for Soulmate Path.

Mandatory:
1. Read AGENTS.md first.
2. Read the relevant sections of Soulmate-Path-DEV-SPEC-v1.md.
3. Inspect and reuse the repository's existing stack and abstractions.
4. Implement only this task plus required direct prerequisites.
5. Do not resolve documented TBDs by guessing.
6. Add/update tests required by the task acceptance criteria.
7. Run relevant lint/typecheck/tests/build.
8. Finish with the AGENTS.md handoff format.

If the task is blocked by missing product input, implement only the non-blocked scaffolding explicitly allowed by TASK-BREAKDOWN.md and report BLOCKED/PARTIAL rather than inventing behavior.
```

## 22. Final rule

Correctness of payment, entitlement, identity, persistence, and generated-asset ownership is more important than finishing a Task ID quickly. When uncertain, preserve the existing stable contract, isolate the ambiguity, and surface it in the handoff.
