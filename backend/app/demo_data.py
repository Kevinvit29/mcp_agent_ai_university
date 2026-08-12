"""Deterministic synthetic university data for local demos and system testing.

The generated identities are fictional.  They must never be mixed with a real
student information system or represented as real people.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, Dict, List

DATA_ORIGIN = "synthetic_demo_v30"
DEMO_PASSWORD = "demo1234"

THAI_GIVEN_NAMES = [
    "Anan", "Araya", "Bodin", "Chalita", "Danai", "Ekapol", "Fah", "Gawin", "Harin", "Inthira",
    "Jirawat", "Kanya", "Lalita", "มนตรี", "Narin", "Ornicha", "Pimchanok", "Qin", "Rachata", "Sasithorn",
    "Thanakorn", "Ubon", "Varin", "Warin", "Yada", "Akarin", "Benjamas", "Chayut", "Duangkamol", "Ekkachai",
    "Fahsai", "Guntita", "Hathai", "Ittipol", "Janya", "Kritsada", "Lalin", "Metha", "Nattapong", "Onuma",
    "Phurin", "Rinrada", "Sirin", "Thanida", "Uthai", "Vichaya", "Wichuda", "Ying", "Zarin", "Ploypailin",
]
THAI_FAMILY_NAMES = [
    "Aksornchai", "Boonmee", "Chantana", "Deeprasert", "Eiamchai", "Fuangfah", "Gajaseni", "Hiranrat", "Inthanon", "Jaturaporn",
    "Kanjanapong", "Limsakul", "Maneesri", "Nimitkul", "Ongkarn", "Phromchai", "Rattanakul", "Sangthong", "Thepsiri", "Udomchai",
    "Vejjajiva", "Wattanakul", "Yotharak", "Aphichat", "Bunyarat", "Chaisomboon", "Dumrong", "Eiamrak", "Fakthong", "Gunasiri",
    "Hemsawat", "Isaraphan", "Jindarat", "Kittipong", "Lertchai", "Mongkol", "Nopparat", "Ounchai", "Pattanakul", "Raksakul",
    "Sukhum", "Tansiri", "Udomsuk", "Vongchai", "Wongsa", "Yimyai", "Ariyakul", "Bunyawat", "Chokdee", "Dhanarak",
    "Eakmongkol", "Fahkram", "Gemsakul", "Hongsakul", "Intarak", "Jirapan", "Kraichai", "Limsom", "Mettakul", "Namsai",
]

PROGRAMS: List[Dict[str, Any]] = [
    {"program_code": "CS", "program_name": "Computer Science", "faculty": "Faculty of Science and Technology", "language": "English", "tuition_fee": "120,000 THB per semester", "courses": [("CS101", "Programming Fundamentals"), ("CS102", "Discrete Mathematics"), ("CS201", "Data Structures"), ("CS202", "Database Systems"), ("CS203", "Web Development"), ("CS301", "Computer Networks"), ("CS302", "Software Engineering"), ("CS303", "Artificial Intelligence")]},
    {"program_code": "DS", "program_name": "Data Science", "faculty": "Faculty of Science and Technology", "language": "English", "tuition_fee": "125,000 THB per semester", "courses": [("DS101", "Introduction to Data Science"), ("DS102", "Statistics for Analytics"), ("DS201", "Python for Data Analysis"), ("DS202", "Data Visualization"), ("DS203", "Machine Learning Foundations"), ("DS301", "Big Data Systems"), ("DS302", "Predictive Analytics"), ("DS303", "Data Ethics")]},
    {"program_code": "BA", "program_name": "Business Administration", "faculty": "International Business School", "language": "English", "tuition_fee": "110,000 THB per semester", "courses": [("BA101", "Principles of Management"), ("BA102", "Business Mathematics"), ("BA201", "Marketing Principles"), ("BA202", "Managerial Accounting"), ("BA203", "Business Communication"), ("BA301", "Operations Management"), ("BA302", "Strategic Management"), ("BA303", "Business Analytics")]},
    {"program_code": "FIN", "program_name": "Finance", "faculty": "International Business School", "language": "English", "tuition_fee": "115,000 THB per semester", "courses": [("FIN101", "Financial Accounting"), ("FIN102", "Microeconomics"), ("FIN201", "Corporate Finance"), ("FIN202", "Investment Analysis"), ("FIN203", "Financial Markets"), ("FIN301", "Portfolio Management"), ("FIN302", "Risk Management"), ("FIN303", "FinTech Applications")]},
    {"program_code": "MKT", "program_name": "Marketing", "faculty": "International Business School", "language": "English", "tuition_fee": "110,000 THB per semester", "courses": [("MKT101", "Marketing Fundamentals"), ("MKT102", "Consumer Behaviour"), ("MKT201", "Digital Marketing"), ("MKT202", "Brand Management"), ("MKT203", "Market Research"), ("MKT301", "Marketing Strategy"), ("MKT302", "Content Marketing"), ("MKT303", "Sales Management")]},
    {"program_code": "LAW", "program_name": "Law", "faculty": "Faculty of Law", "language": "Thai and English", "tuition_fee": "115,000 THB per semester", "courses": [("LAW101", "Introduction to Law"), ("LAW102", "Constitutional Law"), ("LAW201", "Contract Law"), ("LAW202", "Criminal Law"), ("LAW203", "Administrative Law"), ("LAW301", "International Law"), ("LAW302", "Legal Research"), ("LAW303", "Moot Court Practice")]},
    {"program_code": "IR", "program_name": "International Relations", "faculty": "Faculty of Political Science", "language": "English", "tuition_fee": "115,000 THB per semester", "courses": [("IR101", "World Politics"), ("IR102", "International History"), ("IR201", "International Political Economy"), ("IR202", "Diplomacy and Negotiation"), ("IR203", "Regional Studies"), ("IR301", "Foreign Policy Analysis"), ("IR302", "Global Governance"), ("IR303", "Conflict Resolution")]},
    {"program_code": "ENV", "program_name": "Environmental Science", "faculty": "Faculty of Science and Technology", "language": "English", "tuition_fee": "118,000 THB per semester", "courses": [("ENV101", "Earth Systems"), ("ENV102", "Environmental Chemistry"), ("ENV201", "Ecology"), ("ENV202", "Climate Change"), ("ENV203", "Environmental Impact Assessment"), ("ENV301", "Sustainability Management"), ("ENV302", "Water Resource Management"), ("ENV303", "Environmental Policy")]},
    {"program_code": "IE", "program_name": "Industrial Engineering", "faculty": "Faculty of Engineering", "language": "English", "tuition_fee": "125,000 THB per semester", "courses": [("IE101", "Engineering Drawing"), ("IE102", "Calculus for Engineers"), ("IE201", "Production Systems"), ("IE202", "Quality Engineering"), ("IE203", "Operations Research"), ("IE301", "Supply Chain Management"), ("IE302", "Lean Systems"), ("IE303", "Project Engineering")]},
    {"program_code": "HM", "program_name": "Hospitality Management", "faculty": "School of Hospitality and Tourism", "language": "English", "tuition_fee": "112,000 THB per semester", "courses": [("HM101", "Hospitality Fundamentals"), ("HM102", "Service Excellence"), ("HM201", "Food and Beverage Management"), ("HM202", "Hotel Operations"), ("HM203", "Tourism Marketing"), ("HM301", "Revenue Management"), ("HM302", "Event Management"), ("HM303", "Hospitality Strategy")]},
    {"program_code": "GD", "program_name": "Graphic Design", "faculty": "Faculty of Creative Arts", "language": "English", "tuition_fee": "118,000 THB per semester", "courses": [("GD101", "Design Foundations"), ("GD102", "Typography"), ("GD201", "Digital Illustration"), ("GD202", "Visual Communication"), ("GD203", "User Interface Design"), ("GD301", "Brand Identity"), ("GD302", "Motion Graphics"), ("GD303", "Portfolio Studio")]},
    {"program_code": "PSY", "program_name": "Psychology", "faculty": "Faculty of Social Sciences", "language": "English", "tuition_fee": "115,000 THB per semester", "courses": [("PSY101", "Introduction to Psychology"), ("PSY102", "Research Methods"), ("PSY201", "Developmental Psychology"), ("PSY202", "Social Psychology"), ("PSY203", "Cognitive Psychology"), ("PSY301", "Counselling Skills"), ("PSY302", "Psychological Assessment"), ("PSY303", "Health Psychology")]},
]


def student_id_for(index: int) -> str:
    return f"S{index:03d}" if index < 1000 else f"S{index}"


def advisor_id_for(index: int) -> str:
    return f"A{index:03d}"


def _pbkdf2_hash(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 150_000)
    return f"pbkdf2_sha256$150000${salt}${base64.b64encode(digest).decode('ascii')}"


def grade_for(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 85:
        return "A-"
    if score >= 80:
        return "B+"
    if score >= 75:
        return "B"
    if score >= 70:
        return "B-"
    if score >= 65:
        return "C+"
    if score >= 60:
        return "C"
    if score >= 55:
        return "D+"
    if score >= 50:
        return "D"
    return "F"


def synthetic_name(index: int) -> str:
    # Index maths creates unique combinations for the first 3,000 names.
    first = THAI_GIVEN_NAMES[(index - 1) % len(THAI_GIVEN_NAMES)]
    family = THAI_FAMILY_NAMES[((index - 1) // len(THAI_GIVEN_NAMES)) % len(THAI_FAMILY_NAMES)]
    return f"{first} {family}"


def build_demo_dataset(count: int = 1000) -> Dict[str, Any]:
    if count < 1 or count > 5000:
        raise ValueError("count must be between 1 and 5,000")

    # Synthetic local accounts all use one documented demo password. Reusing a
    # deterministic *demo-only* PBKDF2 hash avoids performing 1,040 expensive
    # hash operations every time the 1,000-row dataset is checked or seeded.
    # Real accounts must use unique salts through the normal account-management
    # flow; this is never used in production.
    student_demo_password_hash = _pbkdf2_hash(DEMO_PASSWORD, "synthetic-v30-student-demo")
    advisor_demo_password_hash = _pbkdf2_hash(DEMO_PASSWORD, "synthetic-v30-advisor-demo")

    advisors: List[Dict[str, Any]] = []
    for number in range(1, 41):
        advisor_id = advisor_id_for(number)
        advisors.append({
            "advisor_id": advisor_id,
            "name": synthetic_name(1200 + number),
            "department": PROGRAMS[(number - 1) % len(PROGRAMS)]["faculty"],
            "email": f"advisor.{number:03d}@demo-university.example",
            "phone": f"+66-000-AD{number:03d}",
            "office": f"Academic Building {1 + (number % 5)}, Room {200 + number}",
            "data_origin": DATA_ORIGIN,
            "password_hash": advisor_demo_password_hash,
            "teaches": [],
        })
    advisor_by_id = {row["advisor_id"]: row for row in advisors}

    courses: List[Dict[str, Any]] = []
    for program in PROGRAMS:
        for course_index, (course_code, course_name) in enumerate(program["courses"], start=1):
            advisor_id = advisor_id_for(((len(courses) * 3) % 40) + 1)
            courses.append({
                "course_code": course_code,
                "course_name": course_name,
                "program_code": program["program_code"],
                "program_name": program["program_name"],
                "credits": 3,
                "level": 100 * ((course_index - 1) // 3 + 1),
                "primary_advisor_id": advisor_id,
                "data_origin": DATA_ORIGIN,
            })

    students: List[Dict[str, Any]] = []
    enrollments: List[Dict[str, Any]] = []
    assessments: List[Dict[str, Any]] = []
    attendance: List[Dict[str, Any]] = []
    financial_accounts: List[Dict[str, Any]] = []
    support_cases: List[Dict[str, Any]] = []
    scholarship_awards: List[Dict[str, Any]] = []
    advisor_assignments: Dict[tuple[str, str], Dict[str, Any]] = {}

    for number in range(1, count + 1):
        student_id = student_id_for(number)
        program = PROGRAMS[(number - 1) % len(PROGRAMS)]
        base_gpa = round(2.05 + (((number * 37) % 191) / 100), 2)
        gpa = min(4.0, max(1.8, base_gpa))
        attendance_rate = round(68 + ((number * 17) % 3300) / 100, 2)
        attendance_rate = min(99.5, attendance_rate)
        if gpa < 2.2:
            academic_status, risk_level = "Probation", "High"
        elif gpa < 2.55 or attendance_rate < 74:
            academic_status, risk_level = "At Risk", "Medium"
        elif number % 47 == 0:
            academic_status, risk_level = "Leave of Absence", "Review"
        else:
            academic_status, risk_level = "Active", "Low"
        year_level = 1 + ((number - 1) % 4)
        entry_year = 2027 - year_level
        expected_graduation_year = entry_year + 4
        term_code = "2026-1" if number % 3 else "2026-2"
        credits_earned = min(120, max(0, (year_level - 1) * 30 + (number % 18)))
        scholarship_status = "Merit Scholarship" if gpa >= 3.75 and number % 5 == 0 else ("Need-Based Support" if number % 19 == 0 else "None")
        selected_courses = [program["courses"][(number + offset) % len(program["courses"])] for offset in range(6)]
        subject_grades: List[Dict[str, Any]] = []

        for offset, (course_code, course_name) in enumerate(selected_courses):
            advisor_id = advisor_id_for((((number * 5) + offset * 7) % 40) + 1)
            raw_score = 52 + ((number * 13 + offset * 19) % 4700) / 100
            score = round(min(99.0, max(45.0, raw_score)), 2)
            grade = grade_for(score)
            course_attendance = round(max(55.0, min(100.0, attendance_rate + ((offset * 7) % 13) - 6)), 2)
            grade_row = {
                "course_code": course_code,
                "subject": course_name,
                "grade": grade,
                "score": score,
                "advisor_id": advisor_id,
                "term_code": term_code,
                "credits": 3,
                "attendance_rate": course_attendance,
            }
            subject_grades.append(grade_row)
            enrollments.append({
                "student_id": student_id,
                "course_code": course_code,
                "course_name": course_name,
                "term_code": term_code,
                "advisor_id": advisor_id,
                "grade": grade,
                "score": score,
                "credits": 3,
                "attendance_rate": course_attendance,
                "enrollment_status": "Completed" if number % 7 else "In Progress",
                "data_origin": DATA_ORIGIN,
            })
            attendance.append({
                "student_id": student_id,
                "course_code": course_code,
                "term_code": term_code,
                "advisor_id": advisor_id,
                "attendance_rate": course_attendance,
                "classes_attended": int(round(course_attendance * 0.30)),
                "classes_scheduled": 30,
                "data_origin": DATA_ORIGIN,
            })
            for assessment_type, weight, delta in [
                ("Quiz", 20, -4), ("Midterm", 30, -1), ("Project", 20, 2), ("Final", 30, 3)
            ]:
                assessment_score = round(max(35.0, min(100.0, score + delta + ((number + offset) % 5))), 2)
                assessments.append({
                    "student_id": student_id,
                    "course_code": course_code,
                    "term_code": term_code,
                    "assessment_type": assessment_type,
                    "weight_percent": weight,
                    "score": assessment_score,
                    "advisor_id": advisor_id,
                    "data_origin": DATA_ORIGIN,
                })
            advisor_by_id[advisor_id]["teaches"].append({"student_id": student_id, "subject": course_name, "course_code": course_code})
            advisor_assignments[(advisor_id, course_code)] = {
                "advisor_id": advisor_id,
                "course_code": course_code,
                "term_code": term_code,
                "data_origin": DATA_ORIGIN,
            }

        students.append({
            "student_id": student_id,
            "name": synthetic_name(number),
            "name_th": synthetic_name(number),
            "program": program["program_name"],
            "program_code": program["program_code"],
            "faculty": program["faculty"],
            "gpa": gpa,
            "academic_status": academic_status,
            "year_level": year_level,
            "entry_year": entry_year,
            "expected_graduation_year": expected_graduation_year,
            "academic_term": term_code,
            "credits_earned": credits_earned,
            "credits_required": 120,
            "attendance_rate": attendance_rate,
            "risk_level": risk_level,
            "scholarship_status": scholarship_status,
            "admission_type": ["Portfolio", "Direct Admission", "International Test", "Transfer"][number % 4],
            "campus": ["Bangkok Campus", "City Campus", "Innovation Campus"][number % 3],
            "email": f"student.{student_id.lower()}@demo-university.example",
            "phone": f"+66-000-ST{number:04d}",
            "national_id": f"DEMO-TH-{number:06d}",
            "passport_id": f"DEMO-P-{number:06d}",
            "address": "Synthetic demo address. Not a real residence.",
            "advisor_note": "Synthetic academic note for demonstration and PDPA testing only.",
            "subject_grades": subject_grades,
            "data_origin": DATA_ORIGIN,
            "is_synthetic": True,
            "password_hash": student_demo_password_hash,
        })
        financial_accounts.append({
            "student_id": student_id,
            "term_code": term_code,
            "tuition_due": 110000 + (number % 4) * 5000,
            "amount_paid": 110000 + (number % 4) * 5000 if number % 11 else 55000,
            "balance_due": 0 if number % 11 else 55000,
            "payment_status": "Paid" if number % 11 else "Installment Plan",
            "data_origin": DATA_ORIGIN,
        })
        if risk_level in {"High", "Medium"} or number % 13 == 0:
            support_cases.append({
                "student_id": student_id,
                "case_type": "Academic support" if gpa < 2.55 else "Attendance support",
                "priority": "High" if risk_level == "High" else "Medium",
                "status": "Open" if number % 4 else "Monitoring",
                "assigned_advisor_id": subject_grades[0]["advisor_id"],
                "summary": "Synthetic support record for testing dashboards and role-based access.",
                "data_origin": DATA_ORIGIN,
            })
        if scholarship_status != "None":
            scholarship_awards.append({
                "student_id": student_id,
                "scholarship_name": scholarship_status,
                "term_code": term_code,
                "amount": 25000 if scholarship_status == "Merit Scholarship" else 15000,
                "status": "Approved",
                "data_origin": DATA_ORIGIN,
            })

    return {
        "origin": DATA_ORIGIN,
        "students": students,
        "advisors": advisors,
        "programs": PROGRAMS,
        "courses": courses,
        "enrollments": enrollments,
        "assessments": assessments,
        "attendance": attendance,
        "financial_accounts": financial_accounts,
        "support_cases": support_cases,
        "scholarship_awards": scholarship_awards,
        "advisor_assignments": list(advisor_assignments.values()),
    }
