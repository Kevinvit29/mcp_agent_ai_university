# Agent Orchestrator V9 — Smart Query + AI Route Table UI

## Why this version exists

Debug Trace V7 showed the system was much better, but one class of questions still failed:

```text
list the student that have highest grade program law
```

The previous planner understood that the user was asking about students, but it extracted the wrong study term or missed the ranking purpose. In the trace it could produce:

```json
{
  "operation": "study_term_search",
  "study_term": "list the",
  "ranking": null
}
```

That is wrong. The user purpose is:

```text
Find students in the Law program/subject and rank them by highest sortable grade metric.
```

In this database the sortable numeric grade metric is `gpa`, so the safe plan should be:

```json
{
  "operation": "study_term_search",
  "study_term": "law",
  "ranking": {"field": "gpa", "direction": "desc"},
  "answer_style": "study_rank"
}
```

## What changed

### 1. Smarter study/program term extraction

Updated:

```text
backend/app/agent/aggregate_query.py
```

Now the parser understands phrases such as:

- `give me the name of the student that study law`
- `which students study law`
- `students studying environmental science`
- `find students who take graphic design`
- `list the student that have highest grade program law`
- `law students`

It avoids bad extracted terms such as `list the`, `student`, `name`, or `show`.

### 2. Ranking contract for highest/lowest grade questions

The parser now creates a ranking contract:

```json
{
  "ranking": {
    "field": "gpa",
    "direction": "desc",
    "top_n": 20,
    "metric_label": "GPA"
  }
}
```

For this schema, `highest grade program law` uses GPA because subject grades are letter grades while GPA is numeric and sortable.

### 3. MCP study search now sorts before returning

Updated:

```text
mcp_server/app/tools/mongo_tool.py
```

The `study_term_search` operation now accepts ranking arguments and sorts matching students before returning rows.

### 4. Final answer supports ranked study results

Updated:

```text
backend/app/agent/final_answer_writer.py
```

The response now says the result is ranked by GPA and shows GPA beside each matching student.

### 5. Validator catches generic/wrong study terms

Updated:

```text
backend/app/agent/result_validator.py
```

The validator now rejects tool results if the search term is missing or generic, such as:

```text
list the
student
students
name
```

It also checks that ranking was applied when the user requested highest/lowest.

### 6. Right-side AI route table

Updated:

```text
frontend/src/App.jsx
frontend/src/style.css
```

The side panel now shows a compact AI route table beside the chat:

- Purpose
- Agent
- Tool
- Operation
- Study term
- Filter
- Sort / ranking
- Result count
- Validation

This makes it easier to debug without opening the full trace modal every time.

## Test questions

```text
give me the name of the student that study law
which students study law
how many students study law
list the student that have highest grade program law
students studying environmental science
find students who take graphic design
law students
```

Expected behavior for the highest-grade Law query:

```text
Tool: mongodb_student_tool
Operation: study_term_search
Study term: law
Ranking: GPA desc
Answer style: study_rank
```

## Run

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```
