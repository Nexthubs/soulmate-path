# DECISIONS.md — Soulmate Path Decision Register — v1.2

> Record cross-task product/engineering decisions and the closure of documented TBDs. Do not use this file as a development diary.
> Status values: `OPEN`, `RESOLVED`, `SUPERSEDED`.
> **Precedence:** a `RESOLVED` entry may override the corresponding older baseline in `Soulmate-Path-DEV-SPEC-v1.2.md` only when the entry explicitly states the changed behavior. Keep this file as a delta register, not a second spec.


## Accepted baseline decisions

### QUIZ-01 — Q2/Q3 gender semantics

- **Status:** RESOLVED
- **Date:** 2026-09-22
- **Context:** Excel defines Q2 as the user's gender and Q3 as the gender the user is interested in; PRD uses question 3 for soulmate visuals/sketch.
- **Decision:** `q02 -> user_gender`; `q03 -> preferred_partner_gender`. Sketch gender uses Q3.
- **Rationale:** preserves Excel semantics and PRD behavior without ambiguous `gender` naming.
- **Affected:** Quiz schema, ProfileV1, Email/Subscribe variants, Sketch prompt.
- **Source/evidence:** DEV-SPEC v1.2 / PRD / question workbook.

### PAY-AUTH-01 — Payment entitlement authority

- **Status:** RESOLVED
- **Date:** 2026-09-22
- **Decision:** client PayPal approval is not sufficient. Soulmate entitlement begins from server/provider-confirmed first successful payment.
- **Affected:** SP-403..408, SP-501..505.
- **Source/evidence:** DEV-SPEC v1.2.

### TIME-01 — Unlock time authority

- **Status:** RESOLVED
- **Date:** 2026-09-22
- **Decision:** persisted/server time is authoritative. `sketch_unlock_at = first_payment_completed_at + 12h`; `report_unlock_at = first_payment_completed_at + 24h`. Client time is display-only.
- **Affected:** Result, route guards, Sketch, Report.
- **Source/evidence:** DEV-SPEC v1.2.

### ASSET-01 — Generated asset durability

- **Status:** RESOLVED
- **Date:** 2026-09-22
- **Decision:** successful Sketch output is stored in project-owned durable object storage and revisits return the same asset; provider temporary URLs are not permanent storage.
- **Affected:** SP-603..607.
- **Source/evidence:** DEV-SPEC v1.2.

### ASSET-ACCESS-01 — Production Sketch image access

- **Status:** RESOLVED
- **Date:** 2026-09-27
- **Decision:** production serves Sketch images through one-hour presigned object-storage URLs. Leave `OBJECT_STORAGE_PUBLIC_URL_PREFIX` empty so the asset API uses the existing signed-URL fallback. The production object must not also remain readable through a public R2 domain; disabling the prefix alone changes only the URL issued by the API.
- **Tradeoff:** no stable public CDN cache URL for Sketch images.
- **Affected:** SP-607, RV-03 R-01, M4/M6 storage configuration and acceptance.
- **Source:** product-owner ruling during RV-03 re-review.

### IMGPROVIDER-01 — OpenAI-compatible image endpoint configuration

- **Status:** RESOLVED
- **Date:** 2026-09-26
- **Context:** the deployment will consume `gpt-image-2` through an OpenAI-compatible gateway rather than the official API host; the sketch provider must be pointable at any compatible endpoint without code changes.
- **Decision:** the image provider base URL is configuration (`OPENAI_BASE_URL`, default `https://api.openai.com/v1`, API root without `/images/generations`), alongside `OPENAI_API_KEY` and `SOULMATE_IMAGE_MODEL` (spec target default `gpt-image-2`). The adapter contract, request shape, and error taxonomy remain the DEV-SPEC §25 OpenAI images API; compatible-endpoint behavior is verified at the M4 live-provider gate.
- **Affected:** SP-602, SP-603, M4 review evidence, M6 production configuration.

## Open decisions / TBD register

### PAY-01 — First-month promotional price

- **Status:** OPEN
- **Context:** product requires first month at a promotional price, then regular monthly billing; exact amounts are not in the supplied source materials.
- **Decision:** TBD. Until resolved, use config placeholders `INTRO_PRICE` / `REGULAR_PRICE`; never invent production values.
- **Affected:** SP-303, SP-401, SP-402, M2 production configuration, M6.

### PAY-02 — Re-subscription introductory-price eligibility

- **Status:** OPEN
- **Context:** source materials do not specify whether a returning subscriber can receive the intro price again.
- **Decision:** TBD. Keep eligibility policy configurable/blocked rather than guessing.
- **Affected:** subscription offer selection, historical eligibility query, M6.
- **Update 2026-09-26 (RV follow-up):** under the current `blocked` policy, a same-email second paid session is **not reachable** — the offer is blocked and `confirm`/unknown-subscription reconciliation reject it server-side (`_validate_new_subscription_plan`). If this decision resolves to `single_intro` or `allow_intro`, that path becomes payable and RECOVERY-01 below must be resolved first.

### RECOVERY-01 — Sketch recovery for a second paid session on the same email

- **Status:** OPEN — blocks PAY-02 resolution away from `blocked`
- **Context:** artifact creation dedupes by email (`uq_soulmate_one_sketch_per_email`) while artifact reads are strictly session-scoped (§20 — contact email is not verified identity). A second paid session on the same email therefore receives a REPORT placeholder but its Sketch shows LOCKED with no unlock time, and the create/ensure self-heal cannot fill it (the sketch row belongs to the first session). Isolation is intentional; the recovery path is the open product question.
- **Decision:** TBD. Options: (a) verified-identity recovery flow that binds existing email-scoped assets to the new session after authentication; (b) block the second purchase before payment when the email already owns a sketch; (c) product accepts second-session Sketch as a separate purchasable asset. Do NOT restore bare-email cross-session reads.
- **Affected:** SP-501 (ensure semantics), SP-502/SP-503 (status reads), PAY-02, checkout funnel, M6.
- **Reachability boundary (2026-09-26, RV round-3):** the `blocked` policy blocks OUR offer and binding paths, but it cannot prevent a crafted client from creating a subscription directly at PayPal (client_id/plan are public) and being charged; such a payment stays unbound (confirm 403, events retryable). Refund handling + support are the fallback; this strengthens the case for keeping `blocked` until this decision resolves.
- **Update 2026-09-26 (SP-606):** the generation WRITE path is now identity-level (§11.5): any entitled session of the same normalized email converges on — or may trigger, TIME-01-gated by the asset's persisted `unlock_at` — the single logical sketch generation (`sketch:<email_hash>:v1`; DB uniqueness backstop unchanged). Cross-session READS remain session-scoped and a non-owning session's generate response never exposes the owning session's job/artifact state. The recovery-display product choice (options a/b/c) remains OPEN.
- **Update 2026-09-27 (product owner ruling):** **maintain the current behavior.** The session-scoped read isolation is confirmed **INTENTIONAL and non-defective** — bare-email cross-session reads are and remain PROHIBITED (`不得恢复裸邮箱跨会话读取`). A verified-identity recovery design (magic-link mailbox proof + `soulmate_artifact_access_grants` authorization table, preserving single-asset uniqueness) has been evaluated and is **deferred to a future iteration**; it must go through a dedicated task with high-risk review (identity/entitlement) before implementation. Status stays OPEN solely as the placeholder for that future iteration; the current behavior is the accepted product state, not a defect. This also settles the RV item "second-session LOCKED view" as by-design.

### AGE-01 — Minimum age / DOB eligibility

- **Status:** OPEN
- **Context:** DOB is required, but the supplied requirements do not define an age floor.
- **Decision:** TBD. Validate a real date only until product/legal resolves this.
- **Affected:** Q8 validation, legal/compliance, M1/M6.

### COPY-02 — Transition-2 dynamic copy

- **Status:** OPEN
- **Context:** Figma confirms an Intelligence example; complete mappings for other Q7 options are not provided.
- **Decision:** TBD. Implement mapping infrastructure; do not invent production copy.
- **Affected:** SP-1 UI/copy, M1.

### COPY-03 — Transition-4 dynamic behavior/copy

- **Status:** OPEN
- **Context:** no complete business mapping is supplied.
- **Decision:** TBD. Reproduce supported static Figma behavior only.
- **Affected:** SP-1 UI/copy, M1.

### REPORT-01 — Production report generation model/rules

- **Status:** RESOLVED (2026-09-27, owner decision)
- **Context:** Figma provides report layout, but source requirements do not define a production generator/model.
- **Decision (owner, 2026-09-27):**
  - Generator: OpenAI-compatible chat endpoint (per owner direction recorded 2026-09-27 during SP-702), model `gemma-4-26b` (owner-selected, already configured in env as `SOULMATE_REPORT_MODEL`); endpoint `SOULMATE_REPORT_API_BASE_URL` + `SOULMATE_REPORT_API_KEY` with shared `OPENAI_*` fallback (SP-704 adapter).
  - Generation strategy: **on_demand** (owner-selected; DEV-SPEC §13.4 V1 default confirmed) — the entitled, unlocked user triggers generation from the Report page; the server decides idempotency, mirroring the accepted Sketch queue pattern (§11.5–11.6, `ai_generation_jobs`).
  - Output contract: provider output must validate against `ReportV1` (SP-701) and persists only via `ReportService.save_completed_report` no-clobber semantics (SP-702).
- **Affected:** SP-706 (unblocked for implementation; production switch still gated by REPORT-02), M6.

### REPORT-02 — Production report prompt/content specification

- **Status:** RESOLVED (2026-09-27, owner-supplied final text).
- **Context:** no supported production prompt or report-content mapping exists in supplied requirements (PRD confirms: report page layout + "reading within 24 hours" FAQ only). Owner initially supplied `PRD/Soulmate-Report-Prompt.md`, which on inspection is the Sketch pencil-portrait image prompt (mirror of `config/prompts/soulmate-sketch/v1.txt`), not a report reading prompt — surfaced to the owner, who then authorized a draft and subsequently supplied their own adjusted final text.
- **Required to close (owner to supply):**
  1. The production prompt text (English editorial instruction defining the personalized reading: tone, structure, personalization depth, any prohibited-claim rules).
  2. Any output constraints beyond the `ReportV1` schema (section count, length, forbidden content).
  3. Any safety/compliance framing requirements (e.g. entertainment-purpose wording) — none exists in the PRD.
- **Integration format (fixed by SP-704 machinery):** the supplied text becomes the body of `config/prompts/soulmate-report/<version>.txt` with exactly two whitelisted placeholders — `{profile_json}` (normalized camelCase profile) and `{report_schema_json}` (the ReportV1 JSON schema); no other braces are permitted; template version must match `SOULMATE_REPORT_PROMPT_VERSION`.
- **Approved production prompt (owner final text, 2026-09-27):** `config/prompts/soulmate-report/v1.txt` (sha256 `ba6e6e7eeca9319ec4da186b336a31c64e4ae27d151678e4d042ea71e3e424a2`), template version `v1` = `SOULMATE_REPORT_PROMPT_VERSION`. Content rules fixed by the owner: reflection-not-prediction framing; profile JSON is data never instructions; 4-6 personalization details from the reader's answers; sketch-only fields (birthDate, userGender, preferredPartner*, redFlag, familiarPsychicArtistry, warningResponse) excluded from the report; loveLifeStatus-adaptive framing (single / in_relationship / engaged_or_married / recently_out / complicated); zodiac as symbolism only; exactly four sections ("01."-"04.", 50-90 words each) with exactly three practices in section 03's points; closing <=20 words; no guaranteed outcomes, no medical/psychological/financial/legal advice, plain prose, JSON-only output. Verified against the canonical quiz option codes (q04/q09/q16) and the SP-704 whitelist machinery.
- **Go-live:** `SOULMATE_REPORT_PROMPT_VERSION=v1` + `SOULMATE_REPORT_PROVIDER=openai_compatible` enable generation; SP-706 implements the on_demand trigger/queue; a real provider E2E is the gate evidence.
- **Affected:** SP-704/706, M6.

### PROMPT-01 — Q7 as Sketch `features` input

- **Status:** OPEN
- **Context:** PRD requires Q3/Q5/Q6/Q7 for sketch, but Q7 is a personality quality rather than a visual feature.
- **Current V1 rule:** follow PRD and pass Q7 into `features`; do not reinterpret it.
- **Decision:** product decision required before changing the mapping.
- **Affected:** SP-601/602, sketch quality.

### DOMAIN-01 — Canonical production domain

- **Status:** OPEN
- **Context:** supplied PRD uses both `stell.love` and `stella.love`.
- **Decision:** TBD. Use deployment config `APP_BASE_URL`; no hard-coded canonical host.
- **Affected:** redirects, OAuth/payment return URLs, production deployment.

### LEGAL-01 — Testimonials and statistics

- **Status:** OPEN
- **Context:** PRD explicitly labels testimonial content as fake; landing/subscription UI also contains marketing statistics requiring substantiation.
- **Decision:** production must use truthful approved material or omit it.
- **Affected:** Landing, Subscribe, M6.

### REFUND-01 — Refund policy and cancellation copy

- **Status:** OPEN — provisional draft proposed 2026-09-27 by implementer at owner's request; **awaiting owner approval. No refund statement ships in the UI until approved.**
- **Date:** 2026-09-27
- **Context:** Wave 8 audit (H-3): the SP-804 cancel confirmation asserted "no refund is issued for the current cycle", but §9.8 only mandates stopping future renewals, retaining the paid cycle until `paid_through_at`, and permanently retaining generated content. Those rules do not by themselves authorize a blanket no-refund statement; refunds are handled out-of-band via PayPal dispute/support (SP-409).
- **Decision (approved so far):** the cancel UI makes NO refund claim until the owner approves the policy and final wording below.
- **Provisional draft (NOT approved for shipping) — cancel confirmation dialog, appended after the artifact-retention sentence:**
  > Refund policy: cancelling stops all future billing, and you keep the access you've already paid for. Payments for billing cycles you had access to are non-refundable. If a charge looks wrong, contact our support team or raise it with PayPal.
- **Provisional draft — cancelled-state card (settings), one-liner variant:**
  > Payments for billing cycles you had access to are non-refundable; billing disputes go through our support team or PayPal.
- **Drafting notes for the owner:** (1) the non-refundable phrasing assumes `PAID-THROUGH-01` semantics (users keep what they paid for through `paid_through_at`) — if a prorated/partial-refund policy is ever wanted, this draft must be rewritten; (2) in the dialog, the sentence must render only in the paid branch (unpaid subscriptions have nothing to refund); (3) final wording needs owner sign-off, and the support contact must match the real support channel before shipping.
- **Affected:** SP-804 (`CancelConfirmationDialog`), SP-805 copy, customer support flow, M6 release QA.

### PAID-THROUGH-01 — Guard enforcement vs paid-through access window

- **Status:** RESOLVED
- **Date:** 2026-09-27
- **Owner/approver:** product owner (this session directive)
- **Context:** Wave 8 audit (risk verification): §9.8 DEV DECISION keeps paid entitlement until `paid_through_at`, and the SP-805 settings copy derives "paid access ended" from that date. However, the server route guards granted paid routes based on a confirmed first payment only — they never checked `paid_through_at`, so copy and server behavior could disagree after the paid window ended.
- **Decision:** adopt `paid_through_at` semantics. After cancellation (or any terminal state), paid entitlement remains usable until the end of the current paid cycle (`paid_through_at`), instead of terminating immediately — immediate termination would imply partial-refund logic that the product does not offer. Route guards now deny paid routes (`/result`, `/sketch`, `/report`) only when `paid_through_at` is **known and has passed** on the server clock (TIME-01); a NULL date is "unknown" and never denies (ACTIVE subscriptions normally carry none). Unpaid sessions remain denied via PAY-AUTH-01 regardless of any stored dates. Generated artifacts stay permanently retained (§9.8 + ASSET-01, unchanged).
- **Rationale:** decouples "stop future renewals" from "revoke paid access" exactly as §9.8 intended; avoids implicit partial-refund commitments (refund policy remains `REFUND-01`, OPEN).
- **Affected:** `domain/guard.py`, `guard_service.py`, SP-805 copy consistency, SP-304 guards, M6 review. High-risk evidence: `test_guard_paid_through_window_matrix` + `test_guard_service_enforces_cancelled_paid_through_window` (backend 827/827).
- **Source/evidence:** owner directive 2026-09-27; docs/handoffs/SP-805.md.
- **Supersedes / superseded by:** —

## Decision entry template

```md
### <DECISION-ID> — <title>

- **Status:** OPEN | RESOLVED | SUPERSEDED
- **Date:** YYYY-MM-DD
- **Owner/approver:** <name/role if known>
- **Context:** ...
- **Decision:** ...
- **Rationale:** ...
- **Affected:** <Task IDs / APIs / DB / UI / deployment>
- **Source/evidence:** ...
- **Supersedes / superseded by:** ...
```
