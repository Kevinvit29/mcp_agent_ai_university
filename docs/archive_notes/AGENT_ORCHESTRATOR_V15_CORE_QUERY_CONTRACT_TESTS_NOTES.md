# V15 — Core Query Contract and Regression Tests

## Why this release exists
The previous route could incorrectly treat `how many students in the university` as a study-term aggregate, even though no programme or subject term was supplied. The tool then returned zero results and validation passed only because the high-level domain was still `students`.

## Fixes
- Added a strict total-student-count contract for university-wide count requests.
- Added a university-population aggregate operation for median/average/highest/lowest GPA without a programme/subject filter.
- Kept programme/subject statistics in `study_term_aggregate` only when a meaningful term exists.
- Strengthened validation to compare operation, payload type, scope, statistic, and study term.
- Added a compact `Scope` and `Expected contract` row to the AI route table.
- Added regression tests for the core student-query routes.

## Test commands
```bash
PYTHONPATH=backend python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q backend/app mcp_server/app
npm --prefix frontend run build
```

## Expected examples
- `how many student in the university` → `operation=count`, no study term.
- `average GPA of all students` → `operation=student_population_aggregate`.
- `what is student median grade in law program` → `operation=study_term_aggregate`, `study_term=law`.
