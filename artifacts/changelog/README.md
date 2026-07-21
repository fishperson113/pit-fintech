# Milestone audit trail

This tracked directory is the durable implementation history for the project:

- `PROJECT_STATUS.md`: current project state and gates;
- `CHANGELOG.md`: chronological summary across milestones;
- `milestones/`: detailed implementation log for each milestone.

All other runtime data under `artifacts/` remains ignored by default. The local pre-commit hook
requires these three audit layers whenever an implementation change is staged.
