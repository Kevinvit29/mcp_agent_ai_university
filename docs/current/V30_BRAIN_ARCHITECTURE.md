# V30 Brain and Data Source Map

This is the source-of-truth contract for chat answers in V30. There is no V31
overlay. Changes are made directly in this project.

## Answer pipeline

```text
signed login identity
  -> latest-message purpose contract
  -> deterministic domain/query plan
  -> MCP policy and field minimization
  -> authoritative database query
  -> result-domain and entity validation
  -> deterministic grounded answer
  -> optional natural wording using only verified facts
```

The AI model can help interpret ordinary language, but it cannot choose a wider
role, change the requested student ID, expand fields, or invent database facts.

## Source of truth

| Question | Authoritative source | Tool |
|---|---|---|
| Student identity, program, GPA, academic status, subject grades | MongoDB `students` | `mongodb_student_tool` |
| Advisor identity, department, teaching information | MongoDB `advisors` | `mongodb_advisor_tool` |
| Formal course codes, credits, and course levels | PostgreSQL `course_catalog` | `postgres_university_tool` |
| Enrollment and course status | PostgreSQL `student_course_enrollments` | `postgres_university_tool` |
| Quiz, midterm, project, and final assessment scores | PostgreSQL `student_assessment_results` | `postgres_university_tool` |
| Attendance summaries | PostgreSQL `student_attendance_summaries` | `postgres_university_tool` |
| Tuition/payment balances | PostgreSQL `student_financial_accounts` | `postgres_university_tool` |
| Support cases | PostgreSQL `student_support_cases` | `postgres_university_tool` |
| Scholarships | PostgreSQL `student_scholarship_awards` | `postgres_university_tool` |
| Academic risk aggregates | PostgreSQL `student_profiles` | `postgres_university_tool` |
| Uploaded PDF/Excel/CSV knowledge | PostgreSQL document library and extracted content | `postgres_university_tool` |

PostgreSQL `student_profiles` is the synchronized normalized academic profile.
It supports operational queries, dashboards, and relationships. MongoDB remains
the canonical chat source for master profile, GPA, and subject-grade questions.

## Role scope

| Data | Administrator | Advisor | Student |
|---|---|---|---|
| Master student records | Authorized university scope | Assigned students; minimized fields | Own record |
| GPA | Yes | No | Own |
| Enrollment and assessments | Yes | Assigned courses/students | Own |
| Attendance and academic risk | Yes | Assigned courses/students | Own |
| Finance | Yes | No | Own |
| Scholarships | Yes | No | Own |
| Support cases | Yes | No | No |
| University risk summary | Yes | No | No |
| Formal course catalog | Yes | Yes | Yes |

Scope is enforced in the MCP policy and again in the PostgreSQL/MongoDB query.
The browser cannot expand access by changing a role or student ID in a request.

## Important files

- `academic_query.py`: normalized academic intent parser
- `purpose_contract.py`: latest-message authority
- `contextual_tool_planner.py`: purpose-to-tool routing
- `schema_registry.py`: source and role contract
- `result_validator.py`: payload/domain/entity validation
- `final_answer_writer.py`: grounded answer formatting
- `mcp_server/app/policy.py`: role and section authorization
- `mcp_server/app/tools/postgres_tool.py`: normalized academic retrieval
- `academic_brain_gate.py`: live read-only integration gate

## Verification

Run all backend tests:

```bash
docker compose exec -T backend python -m pytest -q tests
```

Run the academic brain against the live databases:

```bash
docker compose exec -T backend python -m app.agent.academic_brain_gate
```

Run the complete V30 service and application check:

```bash
python3 scripts/v30_control.py check
```

When a database answer is wrong, fix the source map, parser, planner, policy,
retrieval, validator, or formatter and add a regression case. Do not train a
memory rule to conceal a deterministic routing defect.
