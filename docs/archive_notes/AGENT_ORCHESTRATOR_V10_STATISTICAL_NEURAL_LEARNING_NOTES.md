# Agent Orchestrator V10 — Statistical Query + Strong Contract + Neural Learning Refresh

## What V10 fixes

The V9 trace showed that the AI understood the high-level purpose, but the tool planner lost the important term:

- User asked: `what is student median grade in law program`
- Purpose understood: median grade for Law program
- Old tool plan searched: `study_term = "what is"`
- Validation passed incorrectly because it only checked the broad domain `students`

V10 fixes this by making the query contract stronger and adding a student statistics operation.

## New behavior

For questions such as:

- `what is student median grade in law program`
- `average GPA of students who study law`
- `highest GPA in environmental science program`
- `how many students study law`

The planner now creates a statistical plan:

```json
{
  "tool_name": "mongodb_student_tool",
  "operation": "study_term_aggregate",
  "study_term": "law",
  "statistic": "median",
  "metric_field": "gpa",
  "answer_style": "study_statistic"
}
```

## New MCP operation

Added to `mongodb_student_tool`:

```text
study_term_aggregate
```

It filters students by:

- `program` contains study term, or
- `subject_grades.subject` contains study term

Then computes:

- count
- median GPA
- average GPA
- maximum GPA
- minimum GPA

It returns the computed value and supporting student rows.

## Stronger validation

The validator now checks:

- Expected operation is `study_term_aggregate` for statistics questions
- Expected study term matches actual tool result term
- Generic terms such as `what is`, `how many`, or `list the` are rejected
- Expected statistic matches actual statistic

So this should fail and repair instead of passing:

```json
{
  "study_term": "what is",
  "operation": "study_term_search"
}
```

## Neural learning / cloned table agents

The existing database neural/table-agent layer is still enabled:

```env
AUTO_INDEX_EXISTING_DATABASE_AGENTS=true
```

On startup, the backend indexes existing database tables/collections into cloned data agents:

- MongoDB students
- MongoDB advisors
- PostgreSQL programs
- PostgreSQL campus_locations
- PostgreSQL advisor_subjects
- PostgreSQL student_subjects

Uploaded PDF/Excel/CSV files also create their own cloned data agents with semantic chunks and table rows.

This is the practical neural-learning layer for this project. It does not train a new large neural network from zero, but it continuously builds searchable semantic fingerprints for both old and newly uploaded data.

## Improved AI route table

The right-side AI route table now also shows:

- Statistic
- Metric / value
- Study term
- Ranking/filter
- Validation result

This makes it easier to see why an answer was produced.

## Test prompts

Try:

```text
what is student median grade in law program
average GPA of students who study law
highest GPA in law program
how many students study law
give me the name of the student that study law
list the student that have highest grade program law
```

Expected: the trace should show `operation = study_term_aggregate` for statistic questions and `study_term = law`, not `what is`.
