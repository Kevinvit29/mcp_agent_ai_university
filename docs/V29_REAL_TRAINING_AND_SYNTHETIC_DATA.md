# V29: Real Local Training + 1,000 Synthetic University Records

## What is genuinely trained

V29 adds a **real supervised machine-learning model**: a local multilingual intent router built with a character n-gram TF-IDF feature extractor and a small MLP neural network. It is trained, evaluated, versioned, and stored in PostgreSQL (`ai_model_registry`).

It helps choose a safe route such as student data, advisor data, documents, programs, greeting, or general chat. It is a **guarded fallback only**: signed identity checks, PDPA policy checks, and deterministic access rules still decide what data may be read.

It does **not**:

- fine-tune Gemini, OpenAI, or any remote foundation model;
- upload university records to a model provider;
- train on raw student records, messages, passwords, or sensitive fields;
- automatically learn from every user message.

The model learns only from the built-in bilingual starter examples plus corrections that an admin has explicitly reviewed and published.

## Synthetic dataset

The seed script creates a development-only, **fictional** university dataset. All names, emails, phone numbers, national IDs, passport IDs, and addresses are generated demo data and must not be treated as real people or real contact data.

Default dataset size:

| Source | Records |
|---|---:|
| Students | 1,000 |
| Advisors | 40 |
| Programs | 12 |
| Courses | 96 |
| Course enrollments | 6,000 |
| Assessment rows | 24,000 |
| Attendance summaries | 6,000 |
| Financial accounts | 1,000 |
| Support cases | generated subset |
| Scholarship awards | generated subset |

Normalized PostgreSQL tables include program catalog, course catalog, academic terms, student profiles, advisor profiles, advisor-to-course assignments, enrollments, assessments, attendance, finance, support cases, scholarships, and demo provenance metadata. MongoDB retains the role-login/student-record style used by the existing app.

## Seed on a local development machine only

1. Start the containers and wait for `backend`, `mongo`, and `postgres` to be healthy.
2. Run exactly this command from the project folder:

```bash
docker compose exec backend python scripts/seed_synthetic_university_data.py \
  --confirm-synthetic-demo --replace-v28-demo --refresh-ai-index
```

The command refuses `APP_ENV=production`. It intentionally replaces only the old V28 demo student/advisor IDs in the synthetic range `S001`–`S1000` / `A001`–`A040`. Do not run it against any real university database.

Demo accounts after seeding:

```text
Student: S001
Advisor: A001
Password: demo1234
```

Admin login remains controlled by your `.env` values (`ADMIN_USERNAME` / `ADMIN_PASSWORD`); the seed script does not change admin credentials.

## Train or refresh the router

Use the System tab as Admin → **Trainable neural router** → **Train neural router**, or run:

```bash
docker compose exec backend python scripts/train_neural_router.py
```

The automatic local index cycle can also refresh the router when `NEURAL_ROUTER_AUTO_TRAINING=true`.

## Safe production rule

Do not load this synthetic dataset into a production environment. Do not copy generated demo passwords or placeholder PII into a production identity system. For a real deployment, import validated real data through a dedicated migration/ETL process, preserve consent and data-retention rules, and run security/backup tests first.
