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
