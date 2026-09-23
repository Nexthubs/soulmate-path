# AGENTS.md — Soulmate Path

> **Governance version:** 1.2
> **Purpose:** concise execution contract for coding/review agents. Product and technical behavior lives in the DEV-SPEC, not here.

## 1. Document ownership — one fact, one owner

Do not duplicate canonical rules across files. Use these owners:

| File | Owns |
|---|---|
| `AGENTS.md` | how an agent loads context, executes, tests, hands off, and reviews |
| `Soulmate-Path-DEV-SPEC-v1.2.md` | stable product + technical contract |
| `TASK-BREAKDOWN.md` | task scope, dependency, acceptance, context refs, milestone gates |
| `DECISIONS.md` | resolved/open decisions that override or extend the baseline spec |
| `PROJECT-STATE.md` | current milestone, blockers, checkpoints, next safe work |
| `docs/handoffs/SP-xxx.md` | what one task actually changed and verified |
| `docs/reviews/Mx-*.md` | milestone evidence and review conclusion |
| `docs/adr/*.md` | material architecture decisions that are difficult to reverse |

If the same behavior appears in more than one file, treat the owner above as canonical and replace other copies with references when editing documentation.

## 2. Context-loading protocol — selective by default

### 2.1 Always load

For every implementation/review task, read only:

1. `AGENTS.md`.
2. `PROJECT-STATE.md`.
3. The assigned Task block in `TASK-BREAKDOWN.md`.

### 2.2 Then load only task-referenced context

From the Task block, follow:

- `Spec refs` → read only those DEV-SPEC sections.
- `Decision refs` → read only those entries in `DECISIONS.md`.
- `Depends` → read handoffs only for direct dependencies that are actually complete.
- `Figma` → inspect only when the task changes user-visible UI.
- Current milestone review → read only when the task depends on a prior accepted milestone or you are performing review/release work.

### 2.3 Do not eagerly load

Unless the assigned task is cross-cutting architecture/release review, do **not** load:

- the full DEV-SPEC;
- the full TASK-BREAKDOWN;
- every decision;
- every handoff;
- every milestone review;
- unrelated Figma screens.

If a referenced section is insufficient, expand context incrementally and record any newly discovered contract dependency in the task handoff.

## 3. Precedence and conflict handling

For implementation behavior:

1. A `RESOLVED` entry in `DECISIONS.md` overrides the corresponding older DEV-SPEC baseline when it explicitly says so.
2. Otherwise `Soulmate-Path-DEV-SPEC-v1.2.md` is the product/technical contract.
3. `TASK-BREAKDOWN.md` determines the scope and acceptance of the assigned work; it does not redefine product semantics.
4. Existing repository code/conventions determine implementation style, but do not silently override product/payment/security contracts.
5. Handoffs/reviews are implementation evidence, not a place to invent new business rules.

If sources conflict and there is no resolved decision, isolate the conflict, mark the narrow work `BLOCKED` or `PARTIAL`, and add/update a decision entry. Do not guess.

## 4. Task execution protocol

### Before coding

- Confirm the Task ID, `Depends`, `Spec refs`, `Decision refs`, and current status.
- Verify prerequisite code exists in the actual branch; a handoff alone is not proof.
- Inspect the repository's existing framework, routing, DB/migration style, auth/session model, config/secrets, payment abstractions, jobs/queues, storage, analytics, logging, UI primitives, and tests **only as relevant to this task**.
- Reuse existing abstractions before adding dependencies or parallel infrastructure.

### While coding

- Implement the assigned Task plus the minimum direct integration required for correctness.
- Keep domain rules in domain/service code rather than scattering them through views.
- Use stable typed contracts where the repository supports them.
- Persist timestamps in UTC; localize only for presentation.
- Make externally triggered writes idempotent.
- Use DB constraints/transactions for uniqueness and financial/entitlement state where practical.
- Do not hard-code secrets, production prices, provider IDs, or canonical hosts.
- Do not make product decisions to simplify implementation.

### Before finishing

- Re-check every task acceptance criterion.
- Run the narrowest relevant tests, then broader lint/typecheck/build checks required by the repo.
- Verify failure/retry/authorization/idempotency paths when relevant.
- Create/update the mandatory task handoff.
- Update `PROJECT-STATE.md` only if current state/critical path changed.
- Update `DECISIONS.md` only if a cross-task decision/TBD changed.

## 5. Scope discipline

Do not:

- refactor unrelated modules for style;
- rename public contracts without need;
- change Quiz wording/meaning outside approved source/decision changes;
- treat a client payment callback as proof of payment;
- use browser time as authorization for unlocks;
- regenerate an already completed durable Sketch on revisit;
- ship production Report content while its production generator/prompt decisions remain open;
- ship fake/unverified testimonials or statistics;
- weaken tests just to obtain green output.

If a pre-existing bug blocks the task, make the smallest safe fix and record it in the handoff.

## 6. High-risk invariants

These are guardrails, not full domain definitions. Read the referenced DEV-SPEC sections before changing them.

| Area | Invariant | Canonical refs |
|---|---|---|
| Payment | client approval is not entitlement authority; provider/server-confirmed successful payment is required | DEV-SPEC §9–10; `PAY-AUTH-01` |
| Webhooks | verify authenticity; deduplicate provider event IDs; tolerate retry/out-of-order delivery | DEV-SPEC §9.5–9.6 |
| Unlocks | server-persisted time is authoritative | DEV-SPEC §10; `TIME-01` |
| Identity | derive ownership server-side; prevent IDOR | DEV-SPEC §20 |
| Sketch | generation and durable asset creation must be idempotent; revisit returns the same stored asset | DEV-SPEC §11; `ASSET-01` |
| DB | uniqueness required by payment/webhook/answer/artifact contracts should be enforced at DB level where practical | DEV-SPEC §14 |
| Report | production generation stays disabled until its open decisions are resolved | DEV-SPEC §13; `REPORT-01/02` |

Any change to payment, entitlement, webhook verification, DB uniqueness, authorization, generation concurrency, or production configuration requires explicit high-risk review evidence.

## 7. Task states and durable handoff

Task lifecycle:

```text
TODO -> IN_PROGRESS -> REVIEW -> DONE
          |             |
          +-> BLOCKED   +-> IN_PROGRESS  # changes requested
```

`DONE` means implementation **and evidence** are complete. It does not mean the milestone passed.

Every Task moving to `REVIEW` or `DONE` must create/update:

```text
docs/handoffs/<TASK-ID>.md
```

Use `docs/templates/TASK-HANDOFF-TEMPLATE.md`.

The handoff must record only task-specific evidence:

- scope completed / explicitly excluded;
- files/modules changed;
- API/type/schema/config/migration impact;
- acceptance criteria status;
- exact automated/manual checks and results;
- relevant authorization/idempotency/failure-path evidence;
- implementation deviations;
- new risks/TBDs/known limitations;
- direct notes for dependent tasks.

Do not copy large DEV-SPEC sections into a handoff. Link the Task's `Spec refs` instead.

## 8. Milestone review

Milestone requirements/evidence are owned by `TASK-BREAKDOWN.md`. A milestone can become `PASS` only after its required tasks are `DONE` and a durable review exists:

```text
docs/reviews/Mx-<name>-REVIEW.md
```

Use `docs/templates/MILESTONE-REVIEW-TEMPLATE.md`.

Allowed results:

```text
PASS | CONDITIONAL_PASS | BLOCKED
```

The reviewer must inspect current code/diffs plus relevant handoffs/tests/config/migrations. A review that only restates the DEV-SPEC is invalid.

Prefer an independent reviewer for milestone gates. High-risk milestones/changes require a reviewer capable of checking payment/security/concurrency correctness. Model selection is intentionally outside this repository contract.

## 9. Evidence quality

Never write only `tests pass`, `PayPal works`, `Figma matched`, or `idempotency verified`.

Record reproducible evidence, for example:

```text
pnpm test -- soulmate/session.test.ts   PASS 18/18
pnpm typecheck                          PASS
PayPal Sandbox PP-SUB-01                PASS
same webhook replayed x3                1 stored event / 1 business effect
concurrent sketch trigger x10           1 durable artifact
390px visual check                      no P1 mismatch; P2 items linked
```

If credentials/environment/provider/browser access is unavailable, record `NOT_RUN` and the reason. Missing verification cannot be converted into `PASS`.

## 10. `PROJECT-STATE.md`

This is a short operational index, not a second spec. Update it only when one of these changes:

- current milestone/status;
- active or critically blocked tasks;
- latest accepted API/DB/config checkpoint;
- production-disabled capabilities;
- latest accepted review;
- next safe task sequence.

For decision details, link IDs from `DECISIONS.md` rather than repeating their rules.

## 11. `DECISIONS.md`

Use it only for cross-task decisions or TBD closure.

Status values:

```text
OPEN | RESOLVED | SUPERSEDED
```

A resolved decision should identify affected Task IDs/contracts. For a large architecture choice, create an ADR and link it; do not turn the decision register into an essay.

## 12. Review severity

- **P0:** payment/entitlement spoofing, forged webhook acceptance, cross-user data exposure, duplicate charging caused by our logic, destructive loss of paid artifacts.
- **P1:** duplicate Sketch despite uniqueness requirement, wrong Q2/Q3 semantics, client-clock unlock bypass, wrong plan/renewal presentation, lost Quiz recovery, unapproved fake marketing content in production.
- **P2:** non-blocking visual/polish/analytics defects.

An open unwaived P0/P1 blocks milestone/release `PASS` when it affects that gate.

## 13. Standard task prompt

```text
Implement <TASK-ID> from TASK-BREAKDOWN.md.

Mandatory:
1. Read AGENTS.md and PROJECT-STATE.md.
2. Read only the assigned Task block first.
3. Follow that Task's Spec refs / Decision refs / direct dependency handoffs.
4. Inspect and reuse the repository's existing implementation patterns.
5. Do not resolve open decisions by guessing.
6. Implement only assigned scope + minimum direct prerequisites.
7. Add/update tests required by Acceptance.
8. Run relevant checks and record exact results.
9. Create/update docs/handoffs/<TASK-ID>.md.
10. Update PROJECT-STATE.md / DECISIONS.md only when their owned facts changed.

Do not load unrelated project documentation unless the task reveals a concrete dependency on it.
```

## 14. Final rule

Optimize context for relevance, not completeness. Load the smallest sufficient set of contracts, then expand only when implementation evidence shows it is necessary. Correctness of identity, payment, entitlement, persistence, authorization, and durable generated assets takes priority over task speed.
