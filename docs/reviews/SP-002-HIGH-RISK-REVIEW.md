# SP-002 — PostgreSQL Persistence and High-Risk Invariants Review

- **Review result:** PASS
- **Reviewer:** Antigravity High-Risk Invariants Reviewer
- **Date:** 2026-09-23
- **Reviewed branch/commit:** main
- **Milestone source:** `TASK-BREAKDOWN.md` → `SP-002`

## 1. Scope and handoffs reviewed
Required Task IDs:
- SP-002 (PostgreSQL Persistence & High-Risk DB Constraints)

Handoffs:
- `docs/handoffs/SP-002.md`

## 2. Exit criterion
Database schema exists, initial migration succeeds against real PostgreSQL, and all high-risk uniqueness/foreign key constraints are verified with automated tests.

## 3. Current implementation evidence
The repository implements the canonical 9 PostgreSQL tables defined in DEV-SPEC §14 via Alembic migration `backend/alembic/versions/0001_initial_soulmate_schema.py` and SQLAlchemy ORM models in `backend/app/db/models/`.

Key Invariants Enforced at PostgreSQL Database Engine Level:
1. **ASSET-01 (Durable Sketch Uniqueness):** Partial unique index `uq_soulmate_one_sketch_per_email` on `soulmate_artifacts (email_normalized)` WHERE `artifact_type = 'SKETCH'`. Prevents duplicate portrait generation across revisits or sessions.
2. **Answer Deduplication:** Compound unique constraint `uq_soulmate_answers_session_question` on `soulmate_answers (session_id, question_code)`.
3. **Webhook Idempotency:** Unique constraint on `paypal_webhook_events.paypal_event_id`. Ensures replay attacks or retry webhooks do not trigger duplicated downstream effects.
4. **AI Job Idempotency:** Unique constraint on `ai_generation_jobs.idempotency_key`. Prevents duplicate AI generation task queuing.
5. **Subscription & Payment Integrity:** Unique constraints on `subscriptions.provider_subscription_id` and `subscription_payments.provider_payment_id`.
6. **TIME-01 (Timezone Awareness):** All temporal columns use `TIMESTAMP WITH TIME ZONE` (`DateTime(timezone=True)`).
7. **Foreign Key and Query Lookup Performance Indexes:**
   - `soulmate_sessions`: `idx_soulmate_sessions_user_id` on `(user_id)` and `idx_soulmate_sessions_email` on `(email_normalized)`
   - `subscriptions`: `idx_subscriptions_session_id` on `(session_id)`
   - `subscription_payments`: `idx_subscription_payments_subscription_id` on `(subscription_id)`
   - `ai_generation_jobs`: `idx_ai_generation_jobs_artifact_id` on `(artifact_id)`

## 4. Accepted contract checkpoint
- **API:** Internal persistence layer and Alembic schema management
- **Types / schemas:** SQLAlchemy 2.0 type-annotated DeclarativeBase models matching DEV-SPEC §14
- **DB migrations:** `backend/alembic/versions/0001_initial_soulmate_schema.py` (Revision: `0001_initial`)
- **Configuration / provider state:** PostgreSQL 16 on `localhost:5432` with connection URL `postgresql://admin:admin123@localhost:5432/soulmate`

## 5. Required evidence checklist
- [x] All 9 tables exist in database: `test_schema_tables_exist` PASS
- [x] Unique answer constraint: `test_unique_answer_constraint` PASS
- [x] One sketch per email partial unique index: `test_one_sketch_per_email_partial_unique_index` PASS
- [x] Unique PayPal webhook event ID: `test_unique_paypal_event_id` PASS
- [x] Unique AI job idempotency key: `test_unique_idempotency_key_ai_jobs` PASS
- [x] UTC timezone preservation: `test_utc_timestamptz_preservation` PASS
- [x] Unique provider subscription ID: `test_unique_provider_subscription_id` PASS
- [x] Unique provider payment ID: `test_unique_provider_payment_id` PASS
- [x] Foreign key and query lookup indexes: `test_foreign_key_and_query_indexes_exist` PASS
- [x] Reversible Alembic migration: `alembic downgrade base && alembic upgrade head` PASS

## 6. Test / manual / provider evidence
| Check | Result | Evidence/notes |
|---|---|---|
| `pytest backend/tests/test_migrations.py` | PASS | 9/9 automated tests passing against live PostgreSQL 16 instance |
| Schema migration downgrade base | PASS | All 9 tables and indexes cleanly dropped |
| Schema migration upgrade head | PASS | All 9 tables, partial unique index, and foreign key indexes created |
| Partial unique index ASSET-01 | PASS | Enforced by PostgreSQL engine; verified rejecting duplicate sketch while allowing report |
| Timestamps UTC preservation | PASS | Verified `tzinfo` awareness on create and refresh |

## 7. Findings
### P0
- none

### P1
- none

### P2
- none (Audit finding regarding missing foreign key indexes and duplicate `email_normalized` index in models resolved and verified).

## 8. Deviations / unresolved decisions
- None. Schema strictly implements DEV-SPEC §14 and high-risk invariants `ASSET-01`, `TIME-01`, and `PAY-AUTH-01`.

## 9. Rollback / recovery notes
- Migration revision `0001_initial` downgrade drops all tables and indexes cleanly via `alembic downgrade base`.

## 10. Conditions for pass
- None. All requirements and invariant verifications satisfied.

## 11. Next milestone handoff
- Safe API/schema/migration/config checkpoints: Revision `0001_initial` with verified foreign key indexes.
- Capabilities that remain disabled: Report generation remains disabled per DEV-SPEC §13.
- Next safe Task IDs: SP-003, SP-004, SP-005, SP-101.

## 12. Review decision
```text
Result: PASS
Reason: PostgreSQL persistence and all high-risk database invariants verified with 100% green tests against live PostgreSQL 16.
Open P0: 0
Open P1: 0
Next milestone may start: YES
```

## 13. Post-review updates
- [x] `docs/handoffs/SP-002.md` updated
- [x] `PROJECT-STATE.md` updated
- [x] Findings resolved and tested
