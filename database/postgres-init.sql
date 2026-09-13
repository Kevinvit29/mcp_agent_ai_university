CREATE TABLE IF NOT EXISTS programs (
    id SERIAL PRIMARY KEY,
    program_name VARCHAR(100) NOT NULL,
    faculty VARCHAR(100) NOT NULL,
    admission_requirement TEXT NOT NULL,
    tuition_fee VARCHAR(100) NOT NULL,
    language VARCHAR(50) NOT NULL
);

INSERT INTO programs (program_name, faculty, admission_requirement, tuition_fee, language)
VALUES
('Computer Science', 'Faculty of Science and Technology', 'High school diploma or equivalent, English test, mathematics background, portfolio, and interview.', '120,000 THB per semester', 'English'),
('Business Administration', 'International Business School', 'High school diploma or equivalent, English test, statement of purpose, and interview.', '110,000 THB per semester', 'English'),
('International Relations', 'Faculty of Political Science', 'High school diploma or equivalent, English test, writing exam, and interview.', '115,000 THB per semester', 'English')
ON CONFLICT DO NOTHING;

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

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages(session_id, created_at);

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Advisor-owned subject document knowledge base.
-- Admin PDFs stay in admin_documents. Advisor PDFs are separate and are filtered by advisor_id + subject_code.
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_advisor_documents_owner_subject
    ON advisor_documents(advisor_id, subject_code, created_at DESC);

-- Lecturer-owned course material is isolated from advisor-owned knowledge.
CREATE TABLE IF NOT EXISTS lecturer_documents (
    id SERIAL PRIMARY KEY,
    lecturer_id VARCHAR(20) NOT NULL,
    teaching_scope_id VARCHAR(20) NOT NULL,
    subject_code VARCHAR(50) NOT NULL,
    subject_name VARCHAR(255) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    uploaded_by VARCHAR(80) DEFAULT 'LECTURER',
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

CREATE INDEX IF NOT EXISTS idx_lecturer_documents_owner_subject
    ON lecturer_documents(lecturer_id, teaching_scope_id, subject_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lecturer_documents_source_target
    ON lecturer_documents(source_type, storage_target, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_student_subjects_student_subject
    ON student_subjects(student_id, advisor_id, subject_code);

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


-- Optional campus/facility knowledge base for questions like "where is cafeteria?"
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

-- Neural-style data-agent layer for uploaded PDF/Excel/CSV files.
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

-- V29 real trainable-router registry and normalized academic dataset schema.
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
CREATE INDEX IF NOT EXISTS idx_ai_model_registry_active ON ai_model_registry(is_active, updated_at DESC);

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
CREATE INDEX IF NOT EXISTS idx_course_catalog_program ON course_catalog(program_code, course_code);
CREATE TABLE IF NOT EXISTS advisor_profiles (
    advisor_id VARCHAR(20) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    department VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(80),
    office VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE advisor_profiles ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
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
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
    last_master_import_id UUID,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS last_master_import_id UUID;
ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS idx_student_profiles_program ON student_profiles(program_code, gpa);
CREATE INDEX IF NOT EXISTS idx_student_profiles_risk ON student_profiles(risk_level, academic_status);
CREATE INDEX IF NOT EXISTS idx_student_profiles_attendance ON student_profiles(attendance_rate);

-- Admin-only staged student master-data imports. Document knowledge uploads
-- remain in admin_documents/advisor_documents and never write these tables.
CREATE TABLE IF NOT EXISTS master_import_batches (
    import_id UUID PRIMARY KEY,
    import_type VARCHAR(40) NOT NULL DEFAULT 'student_master',
    filename VARCHAR(255) NOT NULL,
    actor_admin_id VARCHAR(80) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'staged',
    source_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    column_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP,
    rolled_back_at TIMESTAMP,
    failure_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_master_import_batches_created
    ON master_import_batches(created_at DESC);

CREATE TABLE IF NOT EXISTS master_import_rows (
    import_id UUID NOT NULL REFERENCES master_import_batches(import_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    canonical_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(import_id, row_number)
);

CREATE TABLE IF NOT EXISTS master_import_snapshots (
    import_id UUID NOT NULL REFERENCES master_import_batches(import_id) ON DELETE CASCADE,
    student_id VARCHAR(20) NOT NULL,
    postgres_existed BOOLEAN NOT NULL DEFAULT FALSE,
    postgres_record JSONB,
    mongo_existed BOOLEAN NOT NULL DEFAULT FALSE,
    mongo_record JSONB,
    PRIMARY KEY(import_id, student_id)
);
CREATE TABLE IF NOT EXISTS advisor_course_assignments (
    advisor_id VARCHAR(20) NOT NULL,
    course_code VARCHAR(40) NOT NULL,
    term_code VARCHAR(30) NOT NULL,
    data_origin VARCHAR(80) NOT NULL DEFAULT 'manual',
    PRIMARY KEY(advisor_id, course_code, term_code)
);
CREATE INDEX IF NOT EXISTS idx_advisor_course_assignments_course ON advisor_course_assignments(course_code, term_code);
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
CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_advisor ON student_course_enrollments(advisor_id, student_id, term_code);
CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_course ON student_course_enrollments(course_code, term_code);
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
CREATE INDEX IF NOT EXISTS idx_student_assessment_results_student ON student_assessment_results(student_id, term_code);
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
CREATE INDEX IF NOT EXISTS idx_student_attendance_summaries_rate ON student_attendance_summaries(attendance_rate, student_id);
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
CREATE INDEX IF NOT EXISTS idx_student_financial_accounts_status ON student_financial_accounts(payment_status, balance_due);
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
CREATE INDEX IF NOT EXISTS idx_student_support_cases_student ON student_support_cases(student_id, status);
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
CREATE INDEX IF NOT EXISTS idx_student_scholarship_awards_student ON student_scholarship_awards(student_id, term_code);

-- V29.2: administrator accounts are persisted in PostgreSQL.
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
