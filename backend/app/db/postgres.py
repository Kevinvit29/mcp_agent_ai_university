import os
import uuid
import json
import time
import re
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pymongo import MongoClient
from app.agent.neural_embedding import build_schema_text, embed_text, cosine_similarity, embedding_descriptor, configured_embedding_provider, resolve_embedding_provider

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "university_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "university_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "university_pass")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DOCUMENT_COLUMNS_PUBLIC = """
    id, filename, uploaded_by, summary, conclusion_table, extraction_method, detected_language,
    source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at
"""
ADVISOR_DOCUMENT_COLUMNS_PUBLIC = """
    id, advisor_id, subject_code, subject_name, filename, uploaded_by, summary, conclusion_table,
    extraction_method, detected_language, source_type, storage_target, cloned_agent_name,
    structured_data, mongo_object_id, created_at
"""


def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor,
    )


def init_postgres_tables() -> None:
    conn = None
    last_error = None
    for _ in range(30):
        try:
            conn = get_connection()
            break
        except Exception as error:
            last_error = error
            time.sleep(1)
    if conn is None:
        raise last_error

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id UUID UNIQUE NOT NULL,
                    user_role VARCHAR(30) NOT NULL,
                    user_identifier VARCHAR(80),
                    title VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    role VARCHAR(30) NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
                    ON chat_sessions(user_role, user_identifier, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                    ON chat_messages(session_id, created_at, id);

                CREATE TABLE IF NOT EXISTS admin_documents (
                    id SERIAL PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    uploaded_by VARCHAR(80) DEFAULT 'ADMIN',
                    summary TEXT NOT NULL,
                    conclusion_table JSONB DEFAULT '{}'::jsonb,
                    text_preview TEXT,
                    full_text TEXT,
                    extraction_method VARCHAR(80),
                    detected_language VARCHAR(30),
                    source_type VARCHAR(30) DEFAULT 'pdf',
                    storage_target VARCHAR(30) DEFAULT 'postgres',
                    cloned_agent_name VARCHAR(80),
                    structured_data JSONB DEFAULT '{}'::jsonb,
                    mongo_object_id VARCHAR(80),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(80);
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS detected_language VARCHAR(30);
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS source_type VARCHAR(30) DEFAULT 'pdf';
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS storage_target VARCHAR(30) DEFAULT 'postgres';
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS cloned_agent_name VARCHAR(80);
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS structured_data JSONB DEFAULT '{}'::jsonb;
                ALTER TABLE admin_documents
                    ADD COLUMN IF NOT EXISTS mongo_object_id VARCHAR(80);

                CREATE TABLE IF NOT EXISTS advisor_subjects (
                    id SERIAL PRIMARY KEY,
                    advisor_id VARCHAR(20) NOT NULL,
                    subject_code VARCHAR(50) NOT NULL,
                    subject_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(advisor_id, subject_code)
                );

                CREATE TABLE IF NOT EXISTS student_subjects (
                    id SERIAL PRIMARY KEY,
                    student_id VARCHAR(20) NOT NULL,
                    advisor_id VARCHAR(20) NOT NULL,
                    subject_code VARCHAR(50) NOT NULL,
                    subject_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, advisor_id, subject_code)
                );

                CREATE TABLE IF NOT EXISTS advisor_documents (
                    id SERIAL PRIMARY KEY,
                    advisor_id VARCHAR(20) NOT NULL,
                    subject_code VARCHAR(50) NOT NULL,
                    subject_name VARCHAR(255) NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    uploaded_by VARCHAR(80) DEFAULT 'ADVISOR',
                    summary TEXT NOT NULL,
                    conclusion_table JSONB DEFAULT '{}'::jsonb,
                    text_preview TEXT,
                    full_text TEXT,
                    extraction_method VARCHAR(80),
                    detected_language VARCHAR(30),
                    source_type VARCHAR(30) DEFAULT 'pdf',
                    storage_target VARCHAR(30) DEFAULT 'postgres',
                    cloned_agent_name VARCHAR(80),
                    structured_data JSONB DEFAULT '{}'::jsonb,
                    mongo_object_id VARCHAR(80),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(80);
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS detected_language VARCHAR(30);
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS source_type VARCHAR(30) DEFAULT 'pdf';
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS storage_target VARCHAR(30) DEFAULT 'postgres';
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS cloned_agent_name VARCHAR(80);
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS structured_data JSONB DEFAULT '{}'::jsonb;
                ALTER TABLE advisor_documents
                    ADD COLUMN IF NOT EXISTS mongo_object_id VARCHAR(80);

                CREATE INDEX IF NOT EXISTS idx_admin_documents_source_target
                    ON admin_documents(source_type, storage_target, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_advisor_documents_owner_subject
                    ON advisor_documents(advisor_id, subject_code, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_advisor_documents_source_target
                    ON advisor_documents(source_type, storage_target, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_student_subjects_student_subject
                    ON student_subjects(student_id, advisor_id, subject_code);


                CREATE TABLE IF NOT EXISTS ai_learning_memories (
                    id SERIAL PRIMARY KEY,
                    user_role VARCHAR(30) NOT NULL,
                    user_identifier VARCHAR(80) NOT NULL,
                    session_id UUID,
                    original_question TEXT NOT NULL,
                    correction_message TEXT NOT NULL,
                    wrong_answer_excerpt TEXT,
                    learned_domain VARCHAR(80) NOT NULL,
                    negative_domain VARCHAR(80),
                    corrected_question TEXT,
                    confidence NUMERIC DEFAULT 0.9,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    use_count INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ai_learning_memories_lookup
                    ON ai_learning_memories(user_role, user_identifier, is_active, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_learning_memories_domain
                    ON ai_learning_memories(learned_domain, is_active, updated_at DESC);

                CREATE TABLE IF NOT EXISTS ai_data_agents (
                    id SERIAL PRIMARY KEY,
                    agent_key VARCHAR(160) UNIQUE NOT NULL,
                    agent_name VARCHAR(180) NOT NULL,
                    document_scope VARCHAR(30) NOT NULL,
                    document_id INTEGER NOT NULL,
                    source_type VARCHAR(30) DEFAULT 'file',
                    storage_target VARCHAR(30) DEFAULT 'postgres',
                    cloned_agent_name VARCHAR(120),
                    owner_role VARCHAR(30) DEFAULT 'admin',
                    owner_id VARCHAR(80),
                    subject_code VARCHAR(80),
                    subject_name VARCHAR(255),
                    filename VARCHAR(255),
                    table_schema JSONB DEFAULT '{}'::jsonb,
                    capabilities JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ai_data_agents_scope_doc
                    ON ai_data_agents(document_scope, document_id);
                CREATE INDEX IF NOT EXISTS idx_ai_data_agents_owner
                    ON ai_data_agents(owner_role, owner_id, subject_code);

                CREATE TABLE IF NOT EXISTS ai_data_chunks (
                    id SERIAL PRIMARY KEY,
                    agent_key VARCHAR(160) NOT NULL REFERENCES ai_data_agents(agent_key) ON DELETE CASCADE,
                    document_scope VARCHAR(30) NOT NULL,
                    document_id INTEGER NOT NULL,
                    source_type VARCHAR(30) DEFAULT 'file',
                    chunk_type VARCHAR(80) DEFAULT 'chunk',
                    sheet_name VARCHAR(255),
                    row_index INTEGER,
                    page_number INTEGER,
                    chunk_text TEXT NOT NULL,
                    embedding JSONB DEFAULT '[]'::jsonb,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ai_data_chunks_agent
                    ON ai_data_chunks(agent_key, id);
                CREATE INDEX IF NOT EXISTS idx_ai_data_chunks_scope
                    ON ai_data_chunks(document_scope, document_id, source_type);

                -- V18: automatic local semantic-training pipeline state.
                -- This stores only index metadata/fingerprints and never sends rows to Gemini.
                CREATE TABLE IF NOT EXISTS ai_index_source_state (
                    source_key VARCHAR(180) PRIMARY KEY,
                    agent_key VARCHAR(160) NOT NULL,
                    source_kind VARCHAR(40) NOT NULL,
                    content_fingerprint VARCHAR(128) NOT NULL,
                    embedding_provider VARCHAR(40) NOT NULL DEFAULT 'local',
                    embedding_model VARCHAR(120) NOT NULL DEFAULT 'local_hash_vector_v2',
                    row_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    last_change_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );

                CREATE INDEX IF NOT EXISTS idx_ai_index_source_state_agent
                    ON ai_index_source_state(agent_key);

                CREATE TABLE IF NOT EXISTS ai_training_jobs (
                    id SERIAL PRIMARY KEY,
                    job_type VARCHAR(80) NOT NULL,
                    trigger_source VARCHAR(80) NOT NULL,
                    provider VARCHAR(40) NOT NULL DEFAULT 'local',
                    status VARCHAR(30) NOT NULL DEFAULT 'running',
                    sources_checked INTEGER DEFAULT 0,
                    sources_changed INTEGER DEFAULT 0,
                    sources_skipped INTEGER DEFAULT 0,
                    details JSONB DEFAULT '{}'::jsonb,
                    error TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ai_training_jobs_recent
                    ON ai_training_jobs(started_at DESC);

                -- Local supervised routing memory. These are learned from corrections/evaluation
                -- and use free local vectors; they are not a cloud fine-tune.
                CREATE TABLE IF NOT EXISTS ai_router_training_examples (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    label JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source VARCHAR(80) NOT NULL DEFAULT 'system',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ai_router_training_examples_active
                    ON ai_router_training_examples(is_active, created_at DESC);

                CREATE TABLE IF NOT EXISTS ai_router_label_centroids (
                    label_key VARCHAR(180) PRIMARY KEY,
                    label JSONB NOT NULL DEFAULT '{}'::jsonb,
                    embedding JSONB NOT NULL DEFAULT '[]'::jsonb,
                    example_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS campus_locations (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    category VARCHAR(100) NOT NULL,
                    building VARCHAR(255),
                    floor VARCHAR(50),
                    location TEXT,
                    opening_hours VARCHAR(255),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO campus_locations (name, category, building, floor, location, opening_hours, notes) VALUES
                    ('Main Cafeteria', 'Food / Cafeteria', 'Student Center Building', '1st floor', 'Near the main entrance of the Student Center Building', '08:00-17:00 on class days', 'Sample campus data. Replace this with the real university location data.'),
                    ('Library', 'Library', 'Academic Resources Building', '1st-3rd floor', 'Opposite the Student Center Building', '08:30-18:00 on class days', 'Sample campus data. Replace this with real details.')
                ON CONFLICT (name) DO NOTHING;

                INSERT INTO advisor_subjects (advisor_id, subject_code, subject_name) VALUES
                    ('A001', 'PFUND', 'Programming Fundamentals'),
                    ('A001', 'BENGL', 'Business English'),
                    ('A001', 'AWRITE', 'Academic Writing'),
                    ('A002', 'CALC', 'Calculus'),
                    ('A002', 'IPOL', 'International Politics'),
                    ('A003', 'MKT', 'Marketing')
                ON CONFLICT (advisor_id, subject_code) DO NOTHING;

                INSERT INTO student_subjects (student_id, advisor_id, subject_code, subject_name) VALUES
                    ('S001', 'A001', 'PFUND', 'Programming Fundamentals'),
                    ('S001', 'A002', 'CALC', 'Calculus'),
                    ('S002', 'A001', 'BENGL', 'Business English'),
                    ('S002', 'A003', 'MKT', 'Marketing'),
                    ('S003', 'A002', 'IPOL', 'International Politics'),
                    ('S003', 'A001', 'AWRITE', 'Academic Writing')
                ON CONFLICT (student_id, advisor_id, subject_code) DO NOTHING;
                """
            )
            # V26: controlled-learning review layer. Existing active memories remain
            # published; newly learned corrections are saved as candidates until an
            # admin reviews them. Answer feedback is a signal, not an automatic rule.
            cur.execute(
                """
                ALTER TABLE ai_learning_memories
                    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) NOT NULL DEFAULT 'candidate';
                ALTER TABLE ai_learning_memories
                    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(80);
                ALTER TABLE ai_learning_memories
                    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
                ALTER TABLE ai_learning_memories
                    ADD COLUMN IF NOT EXISTS review_note TEXT;
                UPDATE ai_learning_memories
                    SET review_status = 'published'
                    WHERE is_active = TRUE AND review_status = 'candidate' AND reviewed_at IS NULL;

                CREATE TABLE IF NOT EXISTS ai_answer_feedback (
                    id SERIAL PRIMARY KEY,
                    session_id UUID,
                    user_role VARCHAR(30) NOT NULL,
                    user_identifier VARCHAR(80) NOT NULL,
                    question TEXT NOT NULL,
                    answer_excerpt TEXT NOT NULL,
                    rating VARCHAR(30) NOT NULL,
                    note TEXT,
                    selected_tool VARCHAR(120),
                    review_status VARCHAR(30) NOT NULL DEFAULT 'new',
                    reviewed_by VARCHAR(80),
                    reviewed_at TIMESTAMP,
                    review_note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ai_answer_feedback_review
                    ON ai_answer_feedback(review_status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_learning_memories_review
                    ON ai_learning_memories(review_status, is_active, updated_at DESC);

                -- V28: immutable operational audit events. These rows intentionally
                -- exclude chat content, document text, passwords and tokens.
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    request_id VARCHAR(80) NOT NULL,
                    actor_role VARCHAR(30) NOT NULL DEFAULT 'anonymous',
                    actor_id VARCHAR(80) NOT NULL DEFAULT 'anonymous',
                    action VARCHAR(255) NOT NULL,
                    outcome VARCHAR(30) NOT NULL,
                    status_code INTEGER NOT NULL,
                    client_ip_hash VARCHAR(64) NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_audit_logs_created
                    ON audit_logs(created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_actor
                    ON audit_logs(actor_role, actor_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_action
                    ON audit_logs(action, created_at DESC);
                """
            )
            cur.execute(
                """
                -- V30: persisted real supervised neural-router model. The artifact is a
                -- local scikit-learn MLP and contains no student-record training text.
                CREATE TABLE IF NOT EXISTS ai_model_registry (
                    model_name VARCHAR(160) PRIMARY KEY,
                    model_type VARCHAR(160) NOT NULL,
                    model_version VARCHAR(160) NOT NULL,
                    artifact BYTEA NOT NULL,
                    metrics JSONB DEFAULT '{}'::jsonb,
                    training_examples INTEGER NOT NULL DEFAULT 0,
                    class_labels JSONB DEFAULT '[]'::jsonb,
                    data_fingerprint VARCHAR(128) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ai_model_registry_active
                    ON ai_model_registry(is_active, updated_at DESC);

                -- V30 normalized academic demo schema. Values are populated only by the
                -- explicit synthetic seeding command in scripts/seed_synthetic_university_data.py.
                CREATE TABLE IF NOT EXISTS academic_terms (
                    term_code VARCHAR(30) PRIMARY KEY,
                    term_name VARCHAR(160) NOT NULL,
                    start_date DATE,
                    end_date DATE,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual'
                );

                CREATE TABLE IF NOT EXISTS university_program_catalog (
                    program_code VARCHAR(30) PRIMARY KEY,
                    program_name VARCHAR(160) NOT NULL,
                    faculty VARCHAR(180) NOT NULL,
                    language VARCHAR(80) NOT NULL,
                    tuition_fee VARCHAR(100),
                    admission_requirement TEXT,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS course_catalog (
                    course_code VARCHAR(40) PRIMARY KEY,
                    course_name VARCHAR(255) NOT NULL,
                    program_code VARCHAR(30) NOT NULL,
                    program_name VARCHAR(160) NOT NULL,
                    credits INTEGER NOT NULL DEFAULT 3,
                    course_level INTEGER,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_course_catalog_program
                    ON course_catalog(program_code, course_code);

                CREATE TABLE IF NOT EXISTS advisor_profiles (
                    advisor_id VARCHAR(20) PRIMARY KEY,
                    full_name VARCHAR(255) NOT NULL,
                    department VARCHAR(255),
                    email VARCHAR(255),
                    phone VARCHAR(80),
                    office VARCHAR(255),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS student_profiles (
                    student_id VARCHAR(20) PRIMARY KEY,
                    full_name VARCHAR(255) NOT NULL,
                    thai_name VARCHAR(255),
                    program_code VARCHAR(30) NOT NULL,
                    program_name VARCHAR(160) NOT NULL,
                    faculty VARCHAR(180),
                    email VARCHAR(255),
                    phone VARCHAR(80),
                    admission_type VARCHAR(100),
                    year_level INTEGER,
                    entry_year INTEGER,
                    expected_graduation_year INTEGER,
                    academic_status VARCHAR(80),
                    gpa NUMERIC(3,2),
                    credits_earned INTEGER DEFAULT 0,
                    credits_required INTEGER DEFAULT 120,
                    attendance_rate NUMERIC(5,2),
                    risk_level VARCHAR(40),
                    scholarship_status VARCHAR(120),
                    campus VARCHAR(120),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_student_profiles_program
                    ON student_profiles(program_code, gpa);
                CREATE INDEX IF NOT EXISTS idx_student_profiles_risk
                    ON student_profiles(risk_level, academic_status);
                CREATE INDEX IF NOT EXISTS idx_student_profiles_attendance
                    ON student_profiles(attendance_rate);

                CREATE TABLE IF NOT EXISTS advisor_course_assignments (
                    advisor_id VARCHAR(20) NOT NULL,
                    course_code VARCHAR(40) NOT NULL,
                    term_code VARCHAR(30) NOT NULL,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    PRIMARY KEY(advisor_id, course_code, term_code)
                );
                CREATE INDEX IF NOT EXISTS idx_advisor_course_assignments_course
                    ON advisor_course_assignments(course_code, term_code);

                CREATE TABLE IF NOT EXISTS student_course_enrollments (
                    student_id VARCHAR(20) NOT NULL,
                    course_code VARCHAR(40) NOT NULL,
                    course_name VARCHAR(255) NOT NULL,
                    term_code VARCHAR(30) NOT NULL,
                    advisor_id VARCHAR(20) NOT NULL,
                    grade VARCHAR(8),
                    score NUMERIC(5,2),
                    credits INTEGER NOT NULL DEFAULT 3,
                    attendance_rate NUMERIC(5,2),
                    enrollment_status VARCHAR(80),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    PRIMARY KEY(student_id, course_code, term_code)
                );
                CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_advisor
                    ON student_course_enrollments(advisor_id, student_id, term_code);
                CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_course
                    ON student_course_enrollments(course_code, term_code);

                CREATE TABLE IF NOT EXISTS student_assessment_results (
                    student_id VARCHAR(20) NOT NULL,
                    course_code VARCHAR(40) NOT NULL,
                    term_code VARCHAR(30) NOT NULL,
                    assessment_type VARCHAR(80) NOT NULL,
                    weight_percent NUMERIC(5,2),
                    score NUMERIC(5,2),
                    advisor_id VARCHAR(20),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    PRIMARY KEY(student_id, course_code, term_code, assessment_type)
                );
                CREATE INDEX IF NOT EXISTS idx_student_assessment_results_student
                    ON student_assessment_results(student_id, term_code);

                CREATE TABLE IF NOT EXISTS student_attendance_summaries (
                    student_id VARCHAR(20) NOT NULL,
                    course_code VARCHAR(40) NOT NULL,
                    term_code VARCHAR(30) NOT NULL,
                    advisor_id VARCHAR(20),
                    attendance_rate NUMERIC(5,2),
                    classes_attended INTEGER,
                    classes_scheduled INTEGER,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    PRIMARY KEY(student_id, course_code, term_code)
                );
                CREATE INDEX IF NOT EXISTS idx_student_attendance_summaries_rate
                    ON student_attendance_summaries(attendance_rate, student_id);

                CREATE TABLE IF NOT EXISTS student_financial_accounts (
                    student_id VARCHAR(20) NOT NULL,
                    term_code VARCHAR(30) NOT NULL,
                    tuition_due NUMERIC(12,2),
                    amount_paid NUMERIC(12,2),
                    balance_due NUMERIC(12,2),
                    payment_status VARCHAR(80),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    PRIMARY KEY(student_id, term_code)
                );
                CREATE INDEX IF NOT EXISTS idx_student_financial_accounts_status
                    ON student_financial_accounts(payment_status, balance_due);

                CREATE TABLE IF NOT EXISTS student_support_cases (
                    id BIGSERIAL PRIMARY KEY,
                    student_id VARCHAR(20) NOT NULL,
                    case_type VARCHAR(120) NOT NULL,
                    priority VARCHAR(40),
                    status VARCHAR(80),
                    assigned_advisor_id VARCHAR(20),
                    summary TEXT,
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_student_support_cases_student
                    ON student_support_cases(student_id, status);

                CREATE TABLE IF NOT EXISTS student_scholarship_awards (
                    id BIGSERIAL PRIMARY KEY,
                    student_id VARCHAR(20) NOT NULL,
                    scholarship_name VARCHAR(180) NOT NULL,
                    term_code VARCHAR(30),
                    amount NUMERIC(12,2),
                    status VARCHAR(80),
                    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_student_scholarship_awards_student
                    ON student_scholarship_awards(student_id, term_code);


                -- V30: administrator accounts are persisted in PostgreSQL.
                -- Passwords are PBKDF2 hashes; .env is used only once for bootstrap.
                CREATE TABLE IF NOT EXISTS admin_accounts (
                    admin_id VARCHAR(32) PRIMARY KEY,
                    username VARCHAR(80) NOT NULL,
                    display_name VARCHAR(255) NOT NULL DEFAULT 'Administrator',
                    password_hash TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by VARCHAR(80) DEFAULT 'bootstrap',
                    password_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_accounts_username_ci
                    ON admin_accounts (lower(username));
                CREATE INDEX IF NOT EXISTS idx_admin_accounts_active
                    ON admin_accounts(is_active, created_at);

                CREATE TABLE IF NOT EXISTS demo_dataset_metadata (
                    dataset_key VARCHAR(160) PRIMARY KEY,
                    data_origin VARCHAR(80) NOT NULL,
                    student_count INTEGER NOT NULL DEFAULT 0,
                    advisor_count INTEGER NOT NULL DEFAULT 0,
                    course_count INTEGER NOT NULL DEFAULT 0,
                    enrollment_count INTEGER NOT NULL DEFAULT 0,
                    assessment_count INTEGER NOT NULL DEFAULT 0,
                    notice TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
    finally:
        conn.close()


def _user_identifier(user_role: str, student_id: Optional[str], advisor_id: Optional[str]) -> str:
    role = (user_role or "student").lower()
    if role == "student":
        return student_id or "unknown_student"
    if role == "advisor":
        return advisor_id or "unknown_advisor"
    if role == "admin":
        return "ADMIN"
    return "unknown"


def create_chat_session(
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    conn = get_connection()
    role = (user_role or "student").lower()
    identifier = _user_identifier(role, requester_student_id, requester_advisor_id)
    new_session_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_sessions (session_id, user_role, user_identifier, title)
                VALUES (%s, %s, %s, %s)
                """,
                (new_session_id, role, identifier, title or "New chat"),
            )
            conn.commit()
            return new_session_id
    finally:
        conn.close()


def get_or_create_session(
    session_id: Optional[str],
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> str:
    role = (user_role or "student").lower()
    identifier = _user_identifier(role, requester_student_id, requester_advisor_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    """
                    SELECT session_id
                    FROM chat_sessions
                    WHERE session_id = %s AND user_role = %s AND user_identifier = %s
                    """,
                    (session_id, role, identifier),
                )
                row = cur.fetchone()
                if row:
                    return str(row["session_id"])

            cur.execute(
                """
                SELECT session_id
                FROM chat_sessions
                WHERE user_role = %s AND user_identifier = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (role, identifier),
            )
            row = cur.fetchone()
            if row:
                return str(row["session_id"])
    finally:
        conn.close()

    return create_chat_session(role, requester_student_id, requester_advisor_id)


def list_chat_sessions(
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    role = (user_role or "student").lower()
    identifier = _user_identifier(role, requester_student_id, requester_advisor_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    cs.session_id,
                    COALESCE(NULLIF(cs.title, ''), 'New chat') AS title,
                    cs.created_at,
                    cs.updated_at,
                    (
                        SELECT cm.content
                        FROM chat_messages cm
                        WHERE cm.session_id = cs.session_id
                        ORDER BY cm.created_at DESC, cm.id DESC
                        LIMIT 1
                    ) AS last_message
                FROM chat_sessions cs
                WHERE cs.user_role = %s AND cs.user_identifier = %s
                ORDER BY cs.updated_at DESC
                LIMIT %s
                """,
                (role, identifier, limit),
            )
            rows = cur.fetchall()
            return [
                {
                    "session_id": str(row["session_id"]),
                    "title": row.get("title") or "New chat",
                    "last_message": row.get("last_message") or "No messages yet",
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                }
                for row in rows
            ]
    finally:
        conn.close()


def save_chat_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, metadata)
                VALUES (%s, %s, %s, %s)
                """,
                (session_id, role, content, Json(metadata or {})),
            )

            if role == "user" and content.strip():
                title = content.strip().replace("\n", " ")[:60]
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = CURRENT_TIMESTAMP,
                        title = CASE WHEN title IS NULL OR title = 'New chat' OR title LIKE '%% chat'
                                     THEN %s ELSE title END
                    WHERE session_id = %s
                    """,
                    (title, session_id),
                )
            else:
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = %s",
                    (session_id,),
                )
            conn.commit()
    finally:
        conn.close()


def get_chat_history(session_id: str, limit: int = 80) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, metadata, created_at
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
            rows.reverse()
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": row.get("metadata") or {},
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                }
                for row in rows
            ]
    finally:
        conn.close()



def get_latest_debug_trace(
    session_id: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the latest assistant debug trace for a session owned by the current identity."""
    role = (user_role or "student").lower()
    identifier = _user_identifier(role, requester_student_id, requester_advisor_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cm.metadata
                FROM chat_messages cm
                JOIN chat_sessions cs ON cs.session_id = cm.session_id
                WHERE cm.session_id = %s
                  AND cs.user_role = %s
                  AND cs.user_identifier = %s
                  AND cm.role = 'assistant'
                  AND cm.metadata ? 'debug_trace'
                ORDER BY cm.created_at DESC, cm.id DESC
                LIMIT 1
                """,
                (session_id, role, identifier),
            )
            row = cur.fetchone()
            if not row:
                return None
            metadata = row.get("metadata") or {}
            return metadata.get("debug_trace")
    finally:
        conn.close()





def delete_chat_session(
    session_id: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> bool:
    """Delete one chat session only if it belongs to the current logged-in identity."""
    role = (user_role or "student").lower()
    identifier = _user_identifier(role, requester_student_id, requester_advisor_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM chat_sessions
                WHERE session_id = %s AND user_role = %s AND user_identifier = %s
                RETURNING session_id
                """,
                (session_id, role, identifier),
            )
            row = cur.fetchone()
            conn.commit()
            return bool(row)
    finally:
        conn.close()

def save_admin_document(
    filename: str,
    uploaded_by: str,
    summary: str,
    conclusion_table: Dict[str, Any],
    text_preview: str,
    full_text: str,
    extraction_method: str = "unknown",
    detected_language: str = "mixed",
    source_type: str = "pdf",
    storage_target: str = "postgres",
    cloned_agent_name: Optional[str] = None,
    structured_data: Optional[Dict[str, Any]] = None,
    mongo_object_id: Optional[str] = None,
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_documents
                    (filename, uploaded_by, summary, conclusion_table, text_preview, full_text,
                     extraction_method, detected_language, source_type, storage_target,
                     cloned_agent_name, structured_data, mongo_object_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, filename, uploaded_by, summary, conclusion_table, extraction_method,
                          detected_language, source_type, storage_target, cloned_agent_name,
                          structured_data, mongo_object_id, created_at
                """,
                (
                    filename,
                    uploaded_by,
                    summary,
                    Json(conclusion_table),
                    text_preview,
                    full_text,
                    extraction_method,
                    detected_language,
                    source_type,
                    storage_target,
                    cloned_agent_name,
                    Json(structured_data or {}),
                    mongo_object_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _iso_row(row)
    finally:
        conn.close()


def list_admin_documents(limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {DOCUMENT_COLUMNS_PUBLIC}
                FROM admin_documents
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_admin_document(document_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {DOCUMENT_COLUMNS_PUBLIC}, text_preview, full_text
                FROM admin_documents
                WHERE id = %s
                """,
                (document_id,),
            )
            row = cur.fetchone()
            return _iso_row(row) if row else None
    finally:
        conn.close()


def delete_admin_document(document_id: int) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM admin_documents
                WHERE id = %s
                RETURNING id
                """,
                (document_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return bool(row)
    finally:
        conn.close()



# ---------- Advisor-owned subject PDF knowledge base ----------

def _iso_row(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not row:
        return {}
    row = dict(row)
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    return row


def advisor_teaches_subject(advisor_id: str, subject_code: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT advisor_id, subject_code, subject_name
                FROM advisor_subjects
                WHERE advisor_id = %s AND subject_code = %s
                """,
                (advisor_id, subject_code),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def list_advisor_subjects(advisor_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT advisor_id, subject_code, subject_name
                FROM advisor_subjects
                WHERE advisor_id = %s
                ORDER BY subject_name
                """,
                (advisor_id,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def list_student_subjects(student_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT student_id, advisor_id, subject_code, subject_name
                FROM student_subjects
                WHERE student_id = %s
                ORDER BY subject_name
                """,
                (student_id,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def save_advisor_document(
    advisor_id: str,
    subject_code: str,
    subject_name: str,
    filename: str,
    uploaded_by: str,
    summary: str,
    conclusion_table: Dict[str, Any],
    text_preview: str,
    full_text: str,
    extraction_method: str = "unknown",
    detected_language: str = "mixed",
    source_type: str = "pdf",
    storage_target: str = "postgres",
    cloned_agent_name: Optional[str] = None,
    structured_data: Optional[Dict[str, Any]] = None,
    mongo_object_id: Optional[str] = None,
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO advisor_documents
                    (advisor_id, subject_code, subject_name, filename, uploaded_by, summary,
                     conclusion_table, text_preview, full_text, extraction_method, detected_language,
                     source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, advisor_id, subject_code, subject_name, filename, uploaded_by,
                          summary, conclusion_table, extraction_method, detected_language,
                          source_type, storage_target, cloned_agent_name, structured_data,
                          mongo_object_id, created_at
                """,
                (
                    advisor_id,
                    subject_code,
                    subject_name,
                    filename,
                    uploaded_by,
                    summary,
                    Json(conclusion_table),
                    text_preview,
                    full_text,
                    extraction_method,
                    detected_language,
                    source_type,
                    storage_target,
                    cloned_agent_name,
                    Json(structured_data or {}),
                    mongo_object_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _iso_row(row)
    finally:
        conn.close()


def list_advisor_documents_for_advisor(advisor_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {ADVISOR_DOCUMENT_COLUMNS_PUBLIC}
                FROM advisor_documents
                WHERE advisor_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (advisor_id, limit),
            )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def list_student_accessible_documents(student_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.advisor_id, d.subject_code, d.subject_name, d.filename, d.uploaded_by,
                       d.summary, d.conclusion_table, d.extraction_method, d.detected_language,
                       d.source_type, d.storage_target, d.cloned_agent_name, d.structured_data,
                       d.mongo_object_id, d.created_at
                FROM advisor_documents d
                JOIN student_subjects ss
                  ON ss.student_id = %s
                 AND ss.advisor_id = d.advisor_id
                 AND ss.subject_code = d.subject_code
                ORDER BY d.created_at DESC
                LIMIT %s
                """,
                (student_id, limit),
            )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_advisor_document_for_advisor(document_id: int, advisor_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {ADVISOR_DOCUMENT_COLUMNS_PUBLIC}, text_preview, full_text
                FROM advisor_documents
                WHERE id = %s AND advisor_id = %s
                """,
                (document_id, advisor_id),
            )
            row = cur.fetchone()
            return _iso_row(row) if row else None
    finally:
        conn.close()


def get_student_accessible_document(document_id: int, student_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.advisor_id, d.subject_code, d.subject_name, d.filename, d.uploaded_by,
                       d.summary, d.conclusion_table, d.text_preview, d.full_text,
                       d.extraction_method, d.detected_language, d.source_type, d.storage_target,
                       d.cloned_agent_name, d.structured_data, d.mongo_object_id, d.created_at
                FROM advisor_documents d
                JOIN student_subjects ss
                  ON ss.student_id = %s
                 AND ss.advisor_id = d.advisor_id
                 AND ss.subject_code = d.subject_code
                WHERE d.id = %s
                """,
                (student_id, document_id),
            )
            row = cur.fetchone()
            return _iso_row(row) if row else None
    finally:
        conn.close()

def delete_advisor_document_for_advisor(document_id: int, advisor_id: str) -> bool:
    """Advisor can delete only their own subject PDF document."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM advisor_documents
                WHERE id = %s AND advisor_id = %s
                RETURNING id
                """,
                (document_id, advisor_id),
            )
            row = cur.fetchone()
            conn.commit()
            return bool(row)
    finally:
        conn.close()



# ---------- Admin all-knowledge document helpers ----------

def _tag_document_scope(row: Dict[str, Any], scope: str) -> Dict[str, Any]:
    row = _iso_row(row)
    row["document_scope"] = scope
    # Stable UI key because admin_documents and advisor_documents may have the same numeric id.
    row["global_id"] = f"{scope}:{row.get('id')}"
    if scope == "admin":
        row.setdefault("subject_name", "Admin/global")
    return row


def list_all_documents_for_admin(limit: int = 100) -> List[Dict[str, Any]]:
    """Admin can inspect both global PDF/Excel files and advisor subject PDF/Excel files in one panel."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, uploaded_by, summary, conclusion_table, extraction_method, detected_language,
                       source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at
                FROM admin_documents
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            admin_rows = [_tag_document_scope(row, "admin") for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, advisor_id, subject_code, subject_name, filename, uploaded_by,
                       summary, conclusion_table, extraction_method, detected_language, source_type,
                       storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at
                FROM advisor_documents
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            advisor_rows = [_tag_document_scope(row, "advisor") for row in cur.fetchall()]

            combined = admin_rows + advisor_rows
            combined.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return combined[:limit]
    finally:
        conn.close()


def get_any_document_for_admin(document_scope: str, document_id: int) -> Optional[Dict[str, Any]]:
    scope = (document_scope or "").lower().strip()
    if scope in {"admin", "global", "admin_documents"}:
        doc = get_admin_document(document_id)
        return _tag_document_scope(doc, "admin") if doc else None
    if scope in {"advisor", "advisor_documents", "subject"}:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, advisor_id, subject_code, subject_name, filename, uploaded_by,
                           summary, conclusion_table, text_preview, full_text, extraction_method, detected_language,
                           source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at
                    FROM advisor_documents
                    WHERE id = %s
                    """,
                    (document_id,),
                )
                row = cur.fetchone()
                return _tag_document_scope(row, "advisor") if row else None
        finally:
            conn.close()
    return None


def delete_any_document_for_admin(document_scope: str, document_id: int) -> bool:
    scope = (document_scope or "").lower().strip()
    if scope in {"admin", "global", "admin_documents"}:
        return delete_admin_document(document_id)
    if scope in {"advisor", "advisor_documents", "subject"}:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM advisor_documents
                    WHERE id = %s
                    RETURNING id
                    """,
                    (document_id,),
                )
                row = cur.fetchone()
                conn.commit()
                return bool(row)
        finally:
            conn.close()
    return False


# ---------- AI learning memory / mistake correction ----------

def save_ai_learning_memory(
    user_role: str,
    user_identifier: str,
    session_id: Optional[str],
    original_question: str,
    correction_message: str,
    wrong_answer_excerpt: str,
    learned_domain: str,
    negative_domain: Optional[str] = None,
    corrected_question: Optional[str] = None,
    confidence: float = 0.9,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a routing lesson learned from a user correction."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_learning_memories
                    (user_role, user_identifier, session_id, original_question, correction_message,
                     wrong_answer_excerpt, learned_domain, negative_domain, corrected_question,
                     confidence, metadata, use_count, is_active, review_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, FALSE, 'candidate')
                RETURNING id, user_role, user_identifier, session_id, original_question,
                          correction_message, wrong_answer_excerpt, learned_domain, negative_domain,
                          corrected_question, confidence, metadata, use_count, is_active, review_status,
                          reviewed_by, reviewed_at, review_note, created_at, updated_at
                """,
                (
                    user_role,
                    user_identifier,
                    session_id,
                    original_question,
                    correction_message,
                    wrong_answer_excerpt,
                    learned_domain,
                    negative_domain,
                    corrected_question,
                    confidence,
                    Json(metadata or {}),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _iso_row(row)
    finally:
        conn.close()


def search_ai_learning_memories(
    user_role: str,
    user_identifier: str,
    query: str = "",
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return correction memories for this role/identity plus admin-shared rules."""
    # Admin memories can be global; student/advisor memories are identity-bound.
    role = (user_role or "student").lower()
    identifier = user_identifier or "unknown"
    like = f"%{(query or '').lower()[:160]}%"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Pull a small candidate set. Python scoring in learning_memory.py decides which one applies.
            cur.execute(
                """
                SELECT id, user_role, user_identifier, session_id, original_question,
                       correction_message, wrong_answer_excerpt, learned_domain, negative_domain,
                       corrected_question, confidence, metadata, use_count, is_active, review_status,
                       reviewed_by, reviewed_at, review_note, created_at, updated_at
                FROM ai_learning_memories
                WHERE
                    (
                        (user_role = %s AND user_identifier = %s)
                        OR (user_role = 'admin' AND user_identifier = 'ADMIN')
                    )
                    AND is_active = TRUE
                    AND (
                        %s = '%%'
                        OR LOWER(original_question) LIKE %s
                        OR LOWER(corrected_question) LIKE %s
                        OR LOWER(correction_message) LIKE %s
                        OR LOWER(learned_domain) LIKE %s
                    )
                ORDER BY confidence DESC, updated_at DESC, id DESC
                LIMIT %s
                """,
                (role, identifier, like, like, like, like, like, limit),
            )
            rows = [_iso_row(row) for row in cur.fetchall()]

            # If strict LIKE found nothing, return recent high-confidence memories for Python fuzzy scoring.
            if not rows:
                cur.execute(
                    """
                    SELECT id, user_role, user_identifier, session_id, original_question,
                           correction_message, wrong_answer_excerpt, learned_domain, negative_domain,
                           corrected_question, confidence, metadata, use_count, created_at, updated_at
                    FROM ai_learning_memories
                    WHERE
                        (
                            (user_role = %s AND user_identifier = %s)
                            OR (user_role = 'admin' AND user_identifier = 'ADMIN')
                        )
                        AND is_active = TRUE
                    ORDER BY confidence DESC, updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    (role, identifier, limit),
                )
                rows = [_iso_row(row) for row in cur.fetchall()]
            return rows
    finally:
        conn.close()


def mark_ai_learning_memory_used(memory_id: Optional[int]) -> None:
    if not memory_id:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_learning_memories
                SET use_count = COALESCE(use_count, 0) + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (memory_id,),
            )
            conn.commit()
    finally:
        conn.close()


def list_ai_learning_memories(
    user_role: str = "admin",
    user_identifier: str = "ADMIN",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    role = (user_role or "admin").lower()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if role == "admin":
                cur.execute(
                    """
                    SELECT id, user_role, user_identifier, session_id, original_question,
                           correction_message, wrong_answer_excerpt, learned_domain, negative_domain,
                           corrected_question, confidence, metadata, use_count, is_active, review_status,
                           reviewed_by, reviewed_at, review_note, created_at, updated_at
                    FROM ai_learning_memories
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_role, user_identifier, session_id, original_question,
                           correction_message, wrong_answer_excerpt, learned_domain, negative_domain,
                           corrected_question, confidence, metadata, use_count, is_active, review_status,
                           reviewed_by, reviewed_at, review_note, created_at, updated_at
                    FROM ai_learning_memories
                    WHERE user_role = %s AND user_identifier = %s
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    (role, user_identifier, limit),
                )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def deactivate_ai_learning_memory(memory_id: int, user_role: str = "admin", user_identifier: str = "ADMIN") -> bool:
    role = (user_role or "admin").lower()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if role == "admin":
                cur.execute(
                    """
                    UPDATE ai_learning_memories
                    SET is_active = FALSE, review_status = 'paused', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id
                    """,
                    (memory_id,),
                )
            else:
                cur.execute(
                    """
                    UPDATE ai_learning_memories
                    SET is_active = FALSE, review_status = 'paused', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND user_role = %s AND user_identifier = %s
                    RETURNING id
                    """,
                    (memory_id, role, user_identifier),
                )
            row = cur.fetchone()
            conn.commit()
            return bool(row)
    finally:
        conn.close()


# ---------- V26 controlled-learning feedback and review ----------

def save_ai_answer_feedback(
    user_role: str,
    user_identifier: str,
    session_id: Optional[str],
    question: str,
    answer_excerpt: str,
    rating: str,
    note: Optional[str] = None,
    selected_tool: Optional[str] = None,
) -> Dict[str, Any]:
    """Save a small voluntary feedback signal. This never creates a live planner rule."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_answer_feedback
                    (session_id, user_role, user_identifier, question, answer_excerpt, rating, note, selected_tool)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, session_id, user_role, user_identifier, question, answer_excerpt,
                          rating, note, selected_tool, review_status, created_at
                """,
                (session_id, user_role, user_identifier, question, answer_excerpt, rating, note, selected_tool),
            )
            row = _iso_row(cur.fetchone())
            conn.commit()
            return row
    finally:
        conn.close()


def list_ai_answer_feedback(limit: int = 50, review_status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if review_status:
                cur.execute(
                    """
                    SELECT id, session_id, user_role, user_identifier, question, answer_excerpt,
                           rating, note, selected_tool, review_status, reviewed_by, reviewed_at,
                           review_note, created_at
                    FROM ai_answer_feedback
                    WHERE review_status = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (review_status, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, session_id, user_role, user_identifier, question, answer_excerpt,
                           rating, note, selected_tool, review_status, reviewed_by, reviewed_at,
                           review_note, created_at
                    FROM ai_answer_feedback
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def review_ai_learning_memory(memory_id: int, action: str, reviewer: str = "ADMIN", note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    action = (action or "").lower()
    if action not in {"publish", "pause", "dismiss"}:
        raise ValueError("Unsupported learning-memory review action")
    status = {"publish": "published", "pause": "paused", "dismiss": "dismissed"}[action]
    is_active = action == "publish"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_learning_memories
                SET is_active = %s,
                    review_status = %s,
                    reviewed_by = %s,
                    reviewed_at = CURRENT_TIMESTAMP,
                    review_note = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, user_role, user_identifier, original_question, correction_message,
                          learned_domain, corrected_question, confidence, use_count, is_active,
                          review_status, reviewed_by, reviewed_at, review_note, created_at, updated_at
                """,
                (is_active, status, reviewer, note, memory_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _iso_row(row) if row else None
    finally:
        conn.close()


def review_ai_answer_feedback(feedback_id: int, action: str, reviewer: str = "ADMIN", note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    action = (action or "").lower()
    if action not in {"reviewed", "dismissed"}:
        raise ValueError("Unsupported answer-feedback review action")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_answer_feedback
                SET review_status = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP, review_note = %s
                WHERE id = %s
                RETURNING id, rating, review_status, reviewed_by, reviewed_at, review_note
                """,
                (action, reviewer, note, feedback_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _iso_row(row) if row else None
    finally:
        conn.close()


def get_controlled_learning_overview() -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT review_status, COUNT(*)::int AS count
                FROM ai_learning_memories
                GROUP BY review_status
                """
            )
            memory_counts = {str(row["review_status"]): int(row["count"]) for row in cur.fetchall()}
            cur.execute(
                """
                SELECT rating, review_status, COUNT(*)::int AS count
                FROM ai_answer_feedback
                GROUP BY rating, review_status
                """
            )
            feedback_counts: Dict[str, int] = {}
            for row in cur.fetchall():
                feedback_counts[f"{row['rating']}:{row['review_status']}"] = int(row["count"])
            return {
                "memory_counts": memory_counts,
                "feedback_counts": feedback_counts,
                "summary": {
                    "candidate_memories": int(memory_counts.get("candidate", 0)),
                    "published_memories": int(memory_counts.get("published", 0)),
                    "paused_or_dismissed_memories": int(memory_counts.get("paused", 0)) + int(memory_counts.get("dismissed", 0)),
                    "new_feedback": sum(count for key, count in feedback_counts.items() if key.endswith(":new")),
                    "needs_review_feedback": sum(count for key, count in feedback_counts.items() if key.startswith("needs_review:")),
                },
            }
    finally:
        conn.close()


def list_learning_review_queue(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_role, original_question, correction_message, learned_domain,
                       corrected_question, confidence, use_count, is_active, review_status,
                       reviewed_by, reviewed_at, review_note, created_at, updated_at
                FROM ai_learning_memories
                WHERE review_status = 'candidate'
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()

# ---------- Neural / semantic data-agent layer ----------

def _safe_agent_slug(value: str) -> str:
    import re
    base = re.sub(r"[^A-Za-z0-9]+", "_", (value or "file")).strip("_").upper()
    return (base or "FILE")[:50]


def make_data_agent_key(document_scope: str, document_id: int) -> str:
    return f"{(document_scope or 'admin').lower()}:{int(document_id)}"



def _stable_json(value: Any) -> str:
    """Canonical JSON used to decide whether a local index source changed."""
    def default(obj: Any):
        if isinstance(obj, (datetime,)):
            return obj.isoformat()
        return str(obj)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default)


def _index_fingerprint(*, agent_key: str, chunks: List[Dict[str, Any]], embedding_info: Dict[str, Any]) -> str:
    payload = {
        "agent_key": agent_key,
        "provider": embedding_info.get("provider"),
        "model": embedding_info.get("model"),
        "dimension": embedding_info.get("dimension"),
        "chunks": [
            {
                "type": c.get("chunk_type"),
                "sheet": c.get("sheet_name"),
                "row": c.get("row_index"),
                "page": c.get("page_number"),
                "text": str(c.get("text") or ""),
                "metadata": c.get("metadata") or {},
            }
            for c in chunks
        ],
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8", errors="ignore")).hexdigest()


def _get_index_source_state(cur, source_key: str) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT * FROM ai_index_source_state WHERE source_key = %s", (source_key,))
    row = cur.fetchone()
    return _iso_row(row) if row else None


def _upsert_index_source_state(
    cur,
    *,
    source_key: str,
    agent_key: str,
    source_kind: str,
    fingerprint: str,
    embedding_info: Dict[str, Any],
    row_count: int,
    chunk_count: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    cur.execute(
        """
        INSERT INTO ai_index_source_state
            (source_key, agent_key, source_kind, content_fingerprint, embedding_provider,
             embedding_model, row_count, chunk_count, last_change_detected_at, last_indexed_at, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (source_key) DO UPDATE SET
            agent_key = EXCLUDED.agent_key,
            source_kind = EXCLUDED.source_kind,
            content_fingerprint = EXCLUDED.content_fingerprint,
            embedding_provider = EXCLUDED.embedding_provider,
            embedding_model = EXCLUDED.embedding_model,
            row_count = EXCLUDED.row_count,
            chunk_count = EXCLUDED.chunk_count,
            last_change_detected_at = CURRENT_TIMESTAMP,
            last_indexed_at = CURRENT_TIMESTAMP,
            metadata = EXCLUDED.metadata
        """,
        (
            source_key, agent_key, source_kind, fingerprint,
            str(embedding_info.get("provider") or "local"),
            str(embedding_info.get("model") or "local_hash_vector_v2"),
            int(row_count), int(chunk_count), Json(metadata or {}),
        ),
    )


def create_or_update_data_agent_index(
    *,
    document_scope: str,
    document_id: int,
    filename: str,
    source_type: str,
    storage_target: str,
    cloned_agent_name: str,
    structured_data: Dict[str, Any],
    summary: str = "",
    conclusion_table: Optional[Dict[str, Any]] = None,
    full_text: str = "",
    owner_role: str = "admin",
    owner_id: Optional[str] = None,
    subject_code: Optional[str] = None,
    subject_name: Optional[str] = None,
    embedding_provider: Optional[str] = None,
    skip_unchanged: bool = True,
) -> Dict[str, Any]:
    """Create one semantic/embedding agent per uploaded file/table.

    This is the practical "clone AI for each uploaded table/file" layer: it does
    not train a separate neural model per file, but it creates an agent profile,
    table schema, searchable row/page chunks, and vector fingerprints.  The MCP
    tools can then ask that agent/index first before keyword search.
    """
    structured = dict(structured_data or {})
    if full_text and not structured.get("full_text"):
        structured["full_text"] = full_text
    if not structured.get("filename"):
        structured["filename"] = filename

    schema, chunks = build_schema_text(structured, filename=filename)
    if summary:
        chunks.insert(0, {
            "chunk_type": "summary",
            "sheet_name": None,
            "row_index": None,
            "page_number": None,
            "text": f"File {filename}. Summary: {summary}",
            "metadata": {"summary": summary},
        })
    table = conclusion_table or {}
    if isinstance(table, dict):
        for idx, row in enumerate(table.get("rows") or []):
            if isinstance(row, dict):
                chunks.append({
                    "chunk_type": "ai_explanation_row",
                    "sheet_name": None,
                    "row_index": idx + 1,
                    "page_number": None,
                    "text": f"File {filename}. AI explanation row {idx + 1}. " + " | ".join(f"{k}: {v}" for k, v in row.items()),
                    "metadata": {"row": row},
                })

    agent_key = make_data_agent_key(document_scope, document_id)
    agent_name = f"{_safe_agent_slug(source_type)}_{_safe_agent_slug(storage_target)}_DATA_AGENT_{document_scope.upper()}_{document_id}"
    active_embedding_provider = resolve_embedding_provider(embedding_provider)
    embedding_info = embedding_descriptor(active_embedding_provider)
    capabilities = {
        "semantic_embedding": embedding_info.get("model"),
        "embedding_provider": embedding_info.get("provider"),
        "embedding_dimension": embedding_info.get("dimension"),
        "embedding_fallback": embedding_info.get("fallback"),
        "chunk_count": len(chunks),
        "can_search_rows": source_type == "excel",
        "can_search_pages": source_type == "pdf",
        "uses_uploaded_storage": storage_target,
        "auto_training_mode": "incremental_local_index",
    }
    source_fingerprint = _index_fingerprint(agent_key=agent_key, chunks=chunks, embedding_info=embedding_info)
    source_row_count = int(structured.get("total_rows") or structured.get("row_count") or len(structured.get("rows") or []))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            previous_state = _get_index_source_state(cur, agent_key)
            if skip_unchanged and previous_state and previous_state.get("content_fingerprint") == source_fingerprint:
                cur.execute("SELECT id, agent_key, agent_name, capabilities FROM ai_data_agents WHERE agent_key = %s", (agent_key,))
                existing = cur.fetchone()
                if existing:
                    result = _iso_row(existing)
                    result.update({
                        "indexed_chunk_count": int(previous_state.get("chunk_count") or 0),
                        "skipped_unchanged": True,
                        "training_method": "local_incremental_fingerprint",
                    })
                    conn.commit()
                    return result
            cur.execute(
                """
                INSERT INTO ai_data_agents
                    (agent_key, agent_name, document_scope, document_id, source_type, storage_target,
                     cloned_agent_name, owner_role, owner_id, subject_code, subject_name, filename,
                     table_schema, capabilities)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_key) DO UPDATE SET
                    agent_name = EXCLUDED.agent_name,
                    source_type = EXCLUDED.source_type,
                    storage_target = EXCLUDED.storage_target,
                    cloned_agent_name = EXCLUDED.cloned_agent_name,
                    owner_role = EXCLUDED.owner_role,
                    owner_id = EXCLUDED.owner_id,
                    subject_code = EXCLUDED.subject_code,
                    subject_name = EXCLUDED.subject_name,
                    filename = EXCLUDED.filename,
                    table_schema = EXCLUDED.table_schema,
                    capabilities = EXCLUDED.capabilities,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, agent_key, agent_name, capabilities
                """,
                (agent_key, agent_name, document_scope, int(document_id), source_type, storage_target,
                 cloned_agent_name, owner_role, owner_id, subject_code, subject_name, filename,
                 Json(schema), Json(capabilities)),
            )
            agent_row = _iso_row(cur.fetchone())
            cur.execute("DELETE FROM ai_data_chunks WHERE agent_key = %s", (agent_key,))
            for chunk in chunks[:8000]:
                text = str(chunk.get("text") or "").strip()
                if not text:
                    continue
                cur.execute(
                    """
                    INSERT INTO ai_data_chunks
                        (agent_key, document_scope, document_id, source_type, chunk_type, sheet_name,
                         row_index, page_number, chunk_text, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_key, document_scope, int(document_id), source_type,
                        chunk.get("chunk_type") or "chunk", chunk.get("sheet_name"),
                        chunk.get("row_index"), chunk.get("page_number"), text,
                        Json(embed_text(text, task="document", provider=active_embedding_provider)), Json({**(chunk.get("metadata") or {}), "embedding_provider": embedding_info.get("provider"), "embedding_model": embedding_info.get("model")}),
                    ),
                )
            indexed_chunk_count = min(len(chunks), 8000)
            _upsert_index_source_state(
                cur,
                source_key=agent_key,
                agent_key=agent_key,
                source_kind=source_type,
                fingerprint=source_fingerprint,
                embedding_info=embedding_info,
                row_count=source_row_count,
                chunk_count=indexed_chunk_count,
                metadata={"filename": filename, "storage_target": storage_target, "owner_role": owner_role},
            )
            conn.commit()
            agent_row["indexed_chunk_count"] = indexed_chunk_count
            agent_row["skipped_unchanged"] = False
            agent_row["training_method"] = "local_incremental_fingerprint" if embedding_info.get("provider") == "local" else "remote_embedding_rebuild"
            return agent_row
    finally:
        conn.close()


def list_data_agents(user_role: str = "admin", requester_student_id: Optional[str] = None, requester_advisor_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    role = (user_role or "student").lower()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if role == "admin":
                cur.execute("""
                    SELECT * FROM ai_data_agents ORDER BY updated_at DESC, id DESC LIMIT %s
                """, (limit,))
            elif role == "advisor":
                cur.execute("""
                    SELECT * FROM ai_data_agents
                    WHERE document_scope = 'advisor' AND owner_id = %s
                    ORDER BY updated_at DESC, id DESC LIMIT %s
                """, (requester_advisor_id, limit))
            else:
                cur.execute("""
                    SELECT a.*
                    FROM ai_data_agents a
                    JOIN student_subjects ss
                      ON ss.student_id = %s
                     AND ss.advisor_id = a.owner_id
                     AND ss.subject_code = a.subject_code
                    WHERE a.document_scope = 'advisor'
                    ORDER BY a.updated_at DESC, a.id DESC LIMIT %s
                """, (requester_student_id, limit))
            return [_iso_row(r) for r in cur.fetchall()]
    finally:
        conn.close()


def search_data_agent_chunks(keyword: str, user_role: str = "admin", requester_student_id: Optional[str] = None, requester_advisor_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    q = keyword or ""
    role = (user_role or "student").lower()
    query_vectors: Dict[str, List[float]] = {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if role == "admin":
                cur.execute("""
                    SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id, a.table_schema, a.capabilities
                    FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
                    ORDER BY c.id DESC LIMIT 4000
                """)
            elif role == "advisor":
                cur.execute("""
                    SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id, a.table_schema, a.capabilities
                    FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
                    WHERE a.document_scope = 'advisor' AND a.owner_id = %s
                    ORDER BY c.id DESC LIMIT 2500
                """, (requester_advisor_id,))
            else:
                cur.execute("""
                    SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id, a.table_schema, a.capabilities
                    FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
                    JOIN student_subjects ss
                      ON ss.student_id = %s
                     AND ss.advisor_id = a.owner_id
                     AND ss.subject_code = a.subject_code
                    WHERE a.document_scope = 'advisor'
                    ORDER BY c.id DESC LIMIT 2500
                """, (requester_student_id,))
            rows = cur.fetchall()
    finally:
        conn.close()

    scored: List[Dict[str, Any]] = []
    low = q.lower()
    for row in rows:
        text = str(row.get("chunk_text") or "")
        emb = row.get("embedding") or []
        capabilities = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        provider = str((capabilities or {}).get("embedding_provider") or (row.get("metadata") or {}).get("embedding_provider") or "local").lower()
        if provider not in query_vectors:
            query_vectors[provider] = embed_text(q, task="query", provider=provider)
        score = cosine_similarity(query_vectors[provider], emb)
        # lexical boost for exact terms, so tables still feel precise.
        for token in set(re.findall(r"[a-zA-Z0-9\u0E00-\u0E7F]{3,}", low)):
            if token in text.lower():
                score += 0.08
        if score > 0.02 or not q:
            item = _iso_row(row)
            item["semantic_score"] = round(float(score), 4)
            item["chunk_text"] = text[:2500]
            item.pop("embedding", None)
            scored.append(item)
    scored.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
    return {
        "success": True,
        "type": "neural_data_agent_search",
        "query": q,
        "embedding_models": sorted(query_vectors.keys()) or [configured_embedding_provider()],
        "matches": scored[:limit],
        "match_count": len(scored),
    }


# ---------- Existing database neural/table-agent indexing ----------

_DATABASE_AGENT_IDS = {
    ("database_mongodb", "students"): 100001,
    ("database_mongodb", "advisors"): 100002,
    ("database_postgres", "programs"): 200001,
    ("database_postgres", "campus_locations"): 200002,
    ("database_postgres", "advisor_subjects"): 200003,
    ("database_postgres", "student_subjects"): 200004,
    ("database_postgres", "university_program_catalog"): 200005,
    ("database_postgres", "course_catalog"): 200006,
    ("database_postgres", "student_profiles"): 200007,
    ("database_postgres", "advisor_profiles"): 200008,
    ("database_postgres", "advisor_course_assignments"): 200009,
    ("database_postgres", "student_course_enrollments"): 200010,
    ("database_postgres", "student_attendance_summaries"): 200011,
    ("database_postgres", "student_support_cases"): 200012,
    ("database_postgres", "student_scholarship_awards"): 200013,
    ("database_postgres", "demo_dataset_metadata"): 200014,
}


def _columns_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    seen: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key not in seen and key != "_id":
                seen.append(str(key))
    return seen


def _clean_database_rows(rows: List[Dict[str, Any]], limit: int = 5000) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for row in (rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        copy.pop("_id", None)
        cleaned.append(copy)
    return cleaned


def create_or_update_existing_database_agent(
    *,
    database_name: str,
    table_name: str,
    rows: List[Dict[str, Any]],
    storage_target: str,
    description: str,
    primary_key: Optional[str] = None,
    owner_role: str = "admin",
    owner_id: str = "ADMIN",
    embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a cloned AI/data agent for one existing DB table or collection."""
    document_scope = "database_mongodb" if storage_target == "mongodb" else "database_postgres"
    document_id = _DATABASE_AGENT_IDS.get((document_scope, table_name), abs(hash((document_scope, table_name))) % 900000 + 300000)
    cleaned = _clean_database_rows(rows)
    columns = _columns_from_rows(cleaned)
    structured = {
        "source_type": "database_table",
        "database": database_name,
        "table_name": table_name,
        "row_count": len(rows or []),
        "columns": columns,
        "rows": cleaned,
        "primary_key": primary_key,
        "description": description,
        "tables": [
            {
                "database": database_name,
                "table_name": table_name,
                "row_count": len(rows or []),
                "columns": columns,
                "rows": cleaned,
                "primary_key": primary_key,
                "description": description,
            }
        ],
    }
    return create_or_update_data_agent_index(
        document_scope=document_scope,
        document_id=int(document_id),
        filename=f"{database_name}.{table_name}",
        source_type="database_table",
        storage_target=storage_target,
        cloned_agent_name=f"{storage_target.upper()}_{_safe_agent_slug(table_name)}_TABLE_AGENT",
        structured_data=structured,
        summary=f"Existing {database_name} table/collection {table_name} indexed as a searchable data agent with {len(rows or [])} row(s).",
        conclusion_table={
            "source_type": "database_table",
            "columns": ["Table", "Rows", "Columns", "Purpose"],
            "rows": [{"Table": table_name, "Rows": len(rows or []), "Columns": ", ".join(columns), "Purpose": description}],
        },
        full_text="",
        owner_role=owner_role,
        owner_id=owner_id,
        embedding_provider=embedding_provider,
    )


def sync_existing_database_agents(
    *,
    mongo_uri: str,
    mongo_db_name: str,
    row_limit: int = 5000,
    embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Index current MongoDB and PostgreSQL tables into cloned neural data agents.

    This is the practical implementation of "train the database": it builds
    semantic fingerprints and table-agent profiles for existing rows so the AI
    can search schema/rows before deciding the final query.
    """
    indexed: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
        db = client[mongo_db_name]
        students = list(db["students"].find({}, {"_id": 0}).sort("student_id", 1).limit(row_limit))
        indexed.append(create_or_update_existing_database_agent(
            database_name="MongoDB", table_name="students", rows=students, storage_target="mongodb",
            primary_key="student_id",
            description="Student records including program, GPA, academic status, and nested subject_grades.",
            embedding_provider=embedding_provider,
        ))
        advisors = list(db["advisors"].find({}, {"_id": 0}).sort("advisor_id", 1).limit(row_limit))
        indexed.append(create_or_update_existing_database_agent(
            database_name="MongoDB", table_name="advisors", rows=advisors, storage_target="mongodb",
            primary_key="advisor_id",
            description="Advisor records and teaching/advising information.",
            embedding_provider=embedding_provider,
        ))
    except Exception as exc:
        errors.append(f"MongoDB indexing failed: {exc}")

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                postgres_tables = [
                    ("programs", "id", "Program/faculty/admission/tuition information.", 500),
                    ("campus_locations", "id", "Campus places such as cafeteria, library, buildings, and opening hours.", 500),
                    ("advisor_subjects", "id", "Subjects taught by each advisor.", 1000),
                    ("student_subjects", "id", "Student enrollment visibility mapping to advisor subjects.", 5000),
                    ("university_program_catalog", "program_code", "Normalized university program catalog.", 500),
                    ("course_catalog", "course_code", "Normalized course catalog with credits, level, and program links.", 1000),
                    ("student_profiles", "student_id", "Synthetic/demo academic profiles including risk, attendance, and enrollment status.", 1000),
                    ("advisor_profiles", "advisor_id", "Synthetic/demo advisor profiles and departments.", 500),
                    ("advisor_course_assignments", "id", "Advisor-to-course assignment map.", 1000),
                    ("student_course_enrollments", "id", "Student course enrollments, term, section, advisor, and final grade.", 2000),
                    ("student_attendance_summaries", "id", "Student attendance summaries by course and term.", 2000),
                    ("student_support_cases", "id", "Admin-only synthetic support/risk case metadata.", 1000),
                    ("student_scholarship_awards", "id", "Synthetic scholarship awards and eligibility metadata.", 1000),
                    ("demo_dataset_metadata", "dataset_key", "Synthetic demo dataset provenance and safe-use metadata.", 100),
                ]
                for table_name, pk, desc, table_limit in postgres_tables:
                    try:
                        cur.execute(f"SELECT * FROM {table_name} LIMIT %s", (min(int(row_limit), int(table_limit)),))
                        rows = [dict(r) for r in cur.fetchall()]
                        indexed.append(create_or_update_existing_database_agent(
                            database_name="PostgreSQL", table_name=table_name, rows=rows, storage_target="postgres",
                            primary_key=pk, description=desc, embedding_provider=embedding_provider,
                        ))
                    except Exception as exc:
                        errors.append(f"PostgreSQL table {table_name} indexing failed: {exc}")
        finally:
            conn.close()
    except Exception as exc:
        errors.append(f"PostgreSQL indexing failed: {exc}")

    changed_agent_count = sum(1 for item in indexed if not item.get("skipped_unchanged"))
    skipped_agent_count = sum(1 for item in indexed if item.get("skipped_unchanged"))
    return {
        "success": len(errors) == 0,
        "indexed_agent_count": len(indexed),
        "changed_agent_count": changed_agent_count,
        "skipped_agent_count": skipped_agent_count,
        "indexed_agents": indexed,
        "errors": errors,
        "embedding": embedding_descriptor(resolve_embedding_provider(embedding_provider)),
        "note": "Existing database collections/tables were indexed as cloned AI data agents. This is semantic retrieval training, not chat-model fine-tuning.",
    }

# ---------- V18 automatic local training / incremental index pipeline ----------

def start_training_job(*, job_type: str, trigger_source: str, provider: str = "local") -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_training_jobs (job_type, trigger_source, provider, status)
                VALUES (%s, %s, %s, 'running')
                RETURNING id
                """,
                (job_type, trigger_source, provider),
            )
            row = cur.fetchone() or {}
            conn.commit()
            return int(row.get("id") or 0)
    finally:
        conn.close()


def finish_training_job(
    job_id: int,
    *,
    status: str,
    sources_checked: int = 0,
    sources_changed: int = 0,
    sources_skipped: int = 0,
    details: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    if not job_id:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_training_jobs
                SET status = %s, sources_checked = %s, sources_changed = %s,
                    sources_skipped = %s, details = %s, error = %s,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    status, int(sources_checked), int(sources_changed), int(sources_skipped),
                    Json(details or {}), (error or "")[:2000] or None, int(job_id),
                ),
            )
            conn.commit()
    finally:
        conn.close()


def get_latest_training_job() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ai_training_jobs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return _iso_row(row) if row else None
    finally:
        conn.close()


def list_index_source_states(limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_key, agent_key, source_kind, embedding_provider,
                       embedding_model, row_count, chunk_count,
                       last_change_detected_at, last_indexed_at, metadata
                FROM ai_index_source_state
                ORDER BY last_indexed_at DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            return [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def sync_uploaded_document_agents(*, embedding_provider: Optional[str] = "local") -> Dict[str, Any]:
    """Ensure legacy/new uploaded admin and advisor documents have local agents.

    Upload endpoints already index files immediately. This sync only backfills old
    files and skips unchanged sources using their content fingerprint.
    """
    indexed: List[Dict[str, Any]] = []
    errors: List[str] = []
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM admin_documents ORDER BY id ASC")
            for row in cur.fetchall():
                doc = _iso_row(row)
                try:
                    indexed.append(create_or_update_data_agent_index(
                        document_scope="admin",
                        document_id=int(doc["id"]),
                        filename=str(doc.get("filename") or f"admin-{doc['id']}"),
                        source_type=str(doc.get("source_type") or "file"),
                        storage_target=str(doc.get("storage_target") or "postgres"),
                        cloned_agent_name=str(doc.get("cloned_agent_name") or "ADMIN_DOCUMENT_AGENT"),
                        structured_data=doc.get("structured_data") or {},
                        summary=str(doc.get("summary") or ""),
                        conclusion_table=doc.get("conclusion_table") or {},
                        full_text=str(doc.get("full_text") or ""),
                        owner_role="admin", owner_id="ADMIN", embedding_provider=embedding_provider,
                        skip_unchanged=True,
                    ))
                except Exception as exc:
                    errors.append(f"Admin document {doc.get('id')} indexing failed: {exc}")
            cur.execute("SELECT * FROM advisor_documents ORDER BY id ASC")
            for row in cur.fetchall():
                doc = _iso_row(row)
                try:
                    indexed.append(create_or_update_data_agent_index(
                        document_scope="advisor",
                        document_id=int(doc["id"]),
                        filename=str(doc.get("filename") or f"advisor-{doc['id']}"),
                        source_type=str(doc.get("source_type") or "file"),
                        storage_target=str(doc.get("storage_target") or "postgres"),
                        cloned_agent_name=str(doc.get("cloned_agent_name") or "ADVISOR_DOCUMENT_AGENT"),
                        structured_data=doc.get("structured_data") or {},
                        summary=str(doc.get("summary") or ""),
                        conclusion_table=doc.get("conclusion_table") or {},
                        full_text=str(doc.get("full_text") or ""),
                        owner_role="advisor", owner_id=str(doc.get("advisor_id") or ""),
                        subject_code=doc.get("subject_code"), subject_name=doc.get("subject_name"),
                        embedding_provider=embedding_provider, skip_unchanged=True,
                    ))
                except Exception as exc:
                    errors.append(f"Advisor document {doc.get('id')} indexing failed: {exc}")
    finally:
        conn.close()
    changed = sum(1 for item in indexed if not item.get("skipped_unchanged"))
    return {
        "success": not errors,
        "indexed_agent_count": len(indexed),
        "changed_agent_count": changed,
        "skipped_agent_count": sum(1 for item in indexed if item.get("skipped_unchanged")),
        "errors": errors,
    }


def _normalise_vector(values: List[float]) -> List[float]:
    import math
    if not values:
        return []
    norm = math.sqrt(sum(float(v) * float(v) for v in values)) or 1.0
    return [round(float(v) / norm, 7) for v in values]


def _seed_local_router_examples() -> List[Dict[str, Any]]:
    """Small safe seed set for the zero-cost local routing learner.

    It does not contain private student values; it only teaches query shapes.
    User corrections are added as additional examples during refresh.
    """
    return [
        {"question": "how many students are in the university", "label": {"domain": "students", "operation": "student_population_aggregate", "intent": "count"}},
        {"question": "list all students", "label": {"domain": "students", "operation": "read_students", "intent": "list"}},
        {"question": "what is S001 grade", "label": {"domain": "students", "operation": "read_students", "intent": "read"}},
        {"question": "show S002 profile", "label": {"domain": "students", "operation": "read_students", "intent": "read"}},
        {"question": "how many students study law", "label": {"domain": "students", "operation": "study_term_aggregate", "intent": "count"}},
        {"question": "median GPA in law program", "label": {"domain": "students", "operation": "study_term_aggregate", "intent": "aggregate"}},
        {"question": "highest GPA in business program", "label": {"domain": "students", "operation": "study_term_aggregate", "intent": "rank"}},
        {"question": "find students with GPA lower than 3", "label": {"domain": "students", "operation": "filter_summary", "intent": "filter"}},
        {"question": "list uploaded PDF files", "label": {"domain": "documents", "operation": "list_documents", "intent": "list"}},
        {"question": "find cafeteria location", "label": {"domain": "campus_info", "operation": "campus_search", "intent": "search"}},
        {"question": "สรุปจำนวนนักศึกษาทั้งมหาวิทยาลัย", "label": {"domain": "students", "operation": "student_population_aggregate", "intent": "count"}},
        {"question": "รายชื่อนักเรียนที่เรียน law", "label": {"domain": "students", "operation": "study_term_search", "intent": "list"}},
    ]


def refresh_local_router_learning() -> Dict[str, Any]:
    """Train a small local centroid router from examples and user corrections.

    This is free/offline semantic learning using the local vectorizer. It is a
    routing helper, not a generative neural-network fine-tune.
    """
    examples = _seed_local_router_examples()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT original_question, corrected_question, learned_domain
                FROM ai_learning_memories
                WHERE is_active = TRUE
                ORDER BY updated_at DESC
                LIMIT 500
                """
            )
            for memory in cur.fetchall():
                row = _iso_row(memory)
                question = str(row.get("corrected_question") or row.get("original_question") or "").strip()
                domain = str(row.get("learned_domain") or "").strip()
                if question and domain:
                    examples.append({"question": question, "label": {"domain": domain, "operation": "learned_correction", "intent": "learned"}})

            # Rebuild only system-derived examples; user corrections remain represented by memories.
            cur.execute("DELETE FROM ai_router_training_examples WHERE source = 'v18_seed'")
            for item in examples:
                source = "v18_seed" if item in _seed_local_router_examples() else "learning_memory"
                cur.execute(
                    "INSERT INTO ai_router_training_examples (question, label, source) VALUES (%s, %s, %s)",
                    (item["question"], Json(item["label"]), source),
                )

            cur.execute("SELECT question, label FROM ai_router_training_examples WHERE is_active = TRUE")
            rows = [_iso_row(row) for row in cur.fetchall()]
            groups: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                label = row.get("label") if isinstance(row.get("label"), dict) else {}
                domain = str(label.get("domain") or "unknown")
                operation = str(label.get("operation") or "unknown")
                key = f"{domain}:{operation}"
                vector = embed_text(str(row.get("question") or ""), task="document", provider="local")
                group = groups.setdefault(key, {"label": label, "vectors": []})
                group["vectors"].append(vector)

            cur.execute("DELETE FROM ai_router_label_centroids")
            for key, group in groups.items():
                vectors = group["vectors"]
                if not vectors:
                    continue
                dim = min(len(vector) for vector in vectors)
                mean = [sum(float(vector[i]) for vector in vectors) / len(vectors) for i in range(dim)]
                cur.execute(
                    """
                    INSERT INTO ai_router_label_centroids (label_key, label, embedding, example_count, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """,
                    (key, Json(group["label"]), Json(_normalise_vector(mean)), len(vectors)),
                )
            conn.commit()
            return {"success": True, "example_count": len(rows), "label_count": len(groups), "provider": "local_hash_vector_v2"}
    finally:
        conn.close()


def get_local_router_hint(question: str, minimum_score: float = 0.34) -> Optional[Dict[str, Any]]:
    """Return a non-authoritative locally learned routing hint for trace/planner use."""
    q = (question or "").strip()
    if not q:
        return None
    vector = embed_text(q, task="query", provider="local")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT label_key, label, embedding, example_count FROM ai_router_label_centroids")
            candidates = [_iso_row(row) for row in cur.fetchall()]
    finally:
        conn.close()
    best = None
    for candidate in candidates:
        score = cosine_similarity(vector, candidate.get("embedding") or [])
        if not best or score > best["score"]:
            best = {"label_key": candidate.get("label_key"), "label": candidate.get("label") or {}, "score": round(float(score), 4), "example_count": int(candidate.get("example_count") or 0)}
    if not best or best["score"] < float(minimum_score):
        return None
    return {**best, "source": "local_centroid_router", "authoritative": False}


def run_local_auto_training_cycle(*, mongo_uri: str, mongo_db_name: str, trigger_source: str = "scheduled") -> Dict[str, Any]:
    """Incrementally refresh all table/file agents without Gemini/token usage."""
    job_id = start_training_job(job_type="incremental_semantic_index", trigger_source=trigger_source, provider="local")
    try:
        existing = sync_existing_database_agents(
            mongo_uri=mongo_uri,
            mongo_db_name=mongo_db_name,
            embedding_provider="local",
        )
        documents = sync_uploaded_document_agents(embedding_provider="local")
        router = refresh_local_router_learning()
        neural_router = {"status": "disabled"}
        enabled = str(os.getenv("NEURAL_ROUTER_AUTO_TRAINING", "true")).strip().lower() not in {"0", "false", "no", "off"}
        if enabled:
            try:
                from app.agent.neural_intent_trainer import train_neural_intent_model
                neural_router = train_neural_intent_model(force=False, trigger_source=trigger_source)
            except Exception as exc:
                neural_router = {"success": False, "status": "failed", "error": str(exc)}
        sources_checked = int(existing.get("indexed_agent_count") or 0) + int(documents.get("indexed_agent_count") or 0)
        sources_changed = int(existing.get("changed_agent_count") or 0) + int(documents.get("changed_agent_count") or 0)
        sources_skipped = int(existing.get("skipped_agent_count") or 0) + int(documents.get("skipped_agent_count") or 0)
        errors = list(existing.get("errors") or []) + list(documents.get("errors") or [])
        result = {
            "success": not errors,
            "job_id": job_id,
            "provider": "local",
            "training_method": "incremental_local_semantic_index_centroid_and_neural_router",
            "existing_database": existing,
            "uploaded_documents": documents,
            "local_router_learning": router,
            "neural_router_learning": neural_router,
            "sources_checked": sources_checked,
            "sources_changed": sources_changed,
            "sources_skipped": sources_skipped,
            "errors": errors,
        }
        finish_training_job(
            job_id,
            status="completed" if not errors else "completed_with_errors",
            sources_checked=sources_checked,
            sources_changed=sources_changed,
            sources_skipped=sources_skipped,
            details=result,
            error="; ".join(errors) if errors else None,
        )
        return result
    except Exception as exc:
        finish_training_job(job_id, status="failed", error=str(exc))
        return {"success": False, "job_id": job_id, "provider": "local", "error": str(exc)}
