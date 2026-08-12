// V30 deliberately does not install a second 100-record sample dataset.
// The backend bootstrap creates one verified 1,000-record synthetic dataset in
// both MongoDB and PostgreSQL when DEMO_DATA_MODE=true.
// This init script only prepares empty collections and indexes for a new volume.
db = db.getSiblingDB("university_mongo");

db.createCollection("students");
db.createCollection("advisors");
db.createCollection("system_metadata");

db.students.createIndex({ student_id: 1 }, { unique: true });
db.students.createIndex({ name: 1 });
db.students.createIndex({ program: 1 });
db.students.createIndex({ program_code: 1 });
db.students.createIndex({ gpa: 1 });
db.students.createIndex({ academic_status: 1 });
db.students.createIndex({ risk_level: 1 });
db.students.createIndex({ attendance_rate: 1 });
db.students.createIndex({ "subject_grades.course_code": 1 });
db.students.createIndex({ "subject_grades.advisor_id": 1 });
db.students.createIndex({ data_origin: 1 });
db.advisors.createIndex({ advisor_id: 1 }, { unique: true });
db.advisors.createIndex({ department: 1 });
db.system_metadata.createIndex({ key: 1 }, { unique: true });

print("V30 MongoDB initialized without sample rows. Backend bootstrap owns the verified demo seed.");
