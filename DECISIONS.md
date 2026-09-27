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

- **Status:** OPEN
- **Context:** Figma provides report layout, but source requirements do not define a production generator/model.
- **Decision:** TBD. Implement structured schema/persistence/renderer/provider boundary and fixture only.
- **Affected:** SP-701..706, M5/M6.

### REPORT-02 — Production report prompt/content specification

- **Status:** OPEN
- **Context:** no supported production prompt or report-content mapping exists in supplied requirements.
- **Decision:** TBD. Production report generation remains disabled.
- **Affected:** SP-704/706, M5/M6.

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
