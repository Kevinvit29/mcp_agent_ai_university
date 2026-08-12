# Admin Flexible Multi-Agent Query Planner

This version changes Admin mode from fixed keyword routing into a safer flexible planning flow.

## New flow

```text
Admin message
  ↓
Intent AI
  ↓
Admin Query Planner AI
  ↓
Universal JSON query plan
  ↓
Backend validator / query builder
  ↓
MCP tool
  ↓
MongoDB / PostgreSQL / PDF / campus data
  ↓
Final response AI
```

## Important new files

### `backend/app/agent/query_planner_ai.py`
This is the flexible Database AI planner.

It converts questions like:

```text
name me the person that have gpa lower than 3.0
which student have to improve grade list me 10 student
where is cafeteria
```

into a structured JSON plan such as:

```json
{
  "intent": "query_students",
  "operation": "filter",
  "filters": [
    {"field": "gpa", "operator": "lt", "value": 3.0}
  ],
  "select": ["student_id", "name", "program", "gpa", "academic_status"],
  "limit": 20
}
```

Then the backend converts the plan into a safe MCP tool call.

## What this fixes

Before, this question:

```text
name me the person that have gpa lower than 3.0
```

could wrongly pull all students.

Now it becomes a real MongoDB filter:

```python
{"gpa": {"$lt": 3.0}}
```

So the database returns only matching students.

## Supported flexible examples

```text
name students with GPA lower than 3.0
students lower than 2.50
students above 3.5
which one has the lowest grade
which student has to improve grade list me 10 student
top 10 students
show business students with GPA lower than 2.5
where is cafeteria
show database structure
what PDFs are uploaded
```

## Large result rule

Open-ended filter/list questions fetch enough rows for the backend to know whether a report is needed.

If matching records are more than 20:

```text
Chat shows first 20
Full result goes into generated PDF
```

## Campus/location data

A new optional table was added:

```sql
campus_locations
```

Fields:

```text
name, category, building, floor, location, opening_hours, notes
```

The seed file includes sample rows for cafeteria and library. Replace these with your real university data.

## Safety

The AI planner cannot send any random MongoDB query.

The backend and MCP validate:

- allowed fields
- allowed operators
- safe sort fields
- read-only access
- role permissions

Admin still has full access, but query execution stays structured and controlled.
