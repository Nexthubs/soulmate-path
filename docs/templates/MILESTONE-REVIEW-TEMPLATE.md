# <MILESTONE-ID> — <Milestone name> Review

- **Review result:** PASS | CONDITIONAL_PASS | BLOCKED
- **Reviewer:** <name/agent/session>
- **Date:** YYYY-MM-DD
- **Reviewed branch/commit:** ...
- **Milestone source:** `TASK-BREAKDOWN.md` → `<MILESTONE-ID>`

## 1. Scope and handoffs reviewed
Required Task IDs:
- ...

Handoffs:
- `docs/handoffs/...`

## 2. Exit criterion
Copy only the exact milestone exit criterion from `TASK-BREAKDOWN.md`.

## 3. Current implementation evidence
Describe what the repository actually implements. Do not restate the full DEV-SPEC.

## 4. Accepted contract checkpoint
- **API:** ...
- **Types / schemas:** ...
- **DB migrations:** ...
- **Configuration / provider state:** ...

## 5. Required evidence checklist
Copy the milestone's `Required evidence` list from `TASK-BREAKDOWN.md` and attach concrete evidence/result to each item.

## 6. Test / manual / provider evidence
| Check | Result | Evidence/notes |
|---|---|---|
| | PASS / FAIL / NOT_RUN | |

## 7. Findings
### P0
- none / ...
### P1
- none / ...
### P2
- none / ...

## 8. Deviations / unresolved decisions
- ...

## 9. Rollback / recovery notes
- N/A / ...

## 10. Conditions for pass
For `CONDITIONAL_PASS`, list exact conditions and next gate.

## 11. Next milestone handoff
- Safe API/schema/migration/config checkpoints: ...
- Capabilities that remain disabled: ...
- Next safe Task IDs: ...

## 12. Review decision
```text
Result: PASS | CONDITIONAL_PASS | BLOCKED
Reason: ...
Open P0: 0
Open P1: 0
Next milestone may start: YES | NO | WITH_CONDITIONS
```

## 13. Post-review updates
- [ ] `PROJECT-STATE.md` updated
- [ ] `DECISIONS.md` updated only if decision state changed
- [ ] Findings linked to follow-up Task IDs
