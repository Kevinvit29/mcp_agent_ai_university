"""Trainable local neural intent router for the university assistant.

This module trains a small supervised neural network (scikit-learn MLPClassifier)
on approved, non-sensitive example questions.  It does *not* fine-tune Gemini/OpenAI
or upload university records to a model provider.  The model only predicts a routing
intent and remains non-authoritative: permission checks and deterministic policy
rules still decide what data can be read.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple
import warnings

import joblib
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer

from app.db.postgres import get_connection

MODEL_NAME = "university_neural_intent_router"
MODEL_TYPE = "tfidf_char_ngram_mlp_classifier"
MODEL_VERSION_PREFIX = "v30-neural-router"
ALLOWED_INTENTS = {
    "greeting",
    "student_data",
    "advisor_data",
    "document_qa",
    "program_data",
    "out_of_scope",
}

_MODEL_CACHE: Dict[str, Any] = {"cache_key": None, "model": None, "metadata": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_examples(items: Iterable[Tuple[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    result: List[Dict[str, str]] = []
    for question, intent in items:
        question = " ".join(str(question or "").split()).strip()
        if not question or intent not in ALLOWED_INTENTS:
            continue
        key = (question.lower(), intent)
        if key in seen:
            continue
        seen.add(key)
        result.append({"question": question, "intent": intent, "source": "v30_curated"})
    return result


def curated_training_examples() -> List[Dict[str, str]]:
    """Return a multilingual, non-private starter corpus for real supervised training."""
    student_ids = ["S001", "S035", "S250", "S999", "S1000"]
    advisor_ids = ["A001", "A018", "A040"]
    items: List[Tuple[str, str]] = []

    student_templates = [
        "show {sid} profile", "what is {sid} GPA", "show {sid} grades",
        "student {sid} information", "find {sid} attendance", "does {sid} have a scholarship",
        "show {sid} course enrolments", "what subjects does {sid} study", "show academic record for {sid}",
        "find students below GPA 2.5", "list students who need support", "how many students are on probation",
        "top 10 students by GPA", "show all students in Computer Science", "which students have low attendance",
        "รายงานข้อมูลของ {sid}", "เกรดของ {sid} คืออะไร", "ขอดู GPA ของ {sid}",
        "{sid} เรียนวิชาอะไรบ้าง", "แสดงประวัติการเรียนของ {sid}", "{sid} ได้ทุนไหม",
        "รายชื่อนักศึกษาที่ GPA ต่ำกว่า 2.5", "นักศึกษาคนไหนเสี่ยง", "นักศึกษาที่ขาดเรียนบ่อย",
        "สรุปจำนวนนักศึกษาที่ติด probation", "แสดงรายชื่อนักศึกษาทั้งหมด",
    ]
    for template in student_templates:
        if "{sid}" in template:
            for sid in student_ids:
                items.append((template.format(sid=sid), "student_data"))
        else:
            items.append((template, "student_data"))

    advisor_templates = [
        "show advisor {aid}", "what courses does {aid} teach", "advisor {aid} workload",
        "list all advisors", "find advisor for Calculus", "advisor information",
        "อาจารย์ {aid} สอนวิชาอะไร", "ข้อมูลอาจารย์ {aid}", "รายชื่ออาจารย์ทั้งหมด",
        "อาจารย์คนไหนดูแลวิชา Marketing", "ตารางงานของอาจารย์",
    ]
    for template in advisor_templates:
        if "{aid}" in template:
            for aid in advisor_ids:
                items.append((template.format(aid=aid), "advisor_data"))
        else:
            items.append((template, "advisor_data"))

    document_questions = [
        "list uploaded PDF files", "what documents are uploaded", "summarize the uploaded policy",
        "find the report writing document", "search the Excel attendance file", "explain this PDF",
        "what is inside the selected document", "show the spreadsheet columns", "find syllabus for Calculus",
        "what does the university policy say", "open the uploaded file", "search the database document",
        "มีไฟล์ PDF อะไรบ้าง", "สรุปเอกสารที่อัปโหลด", "ค้นหาไฟล์ Excel", "ในเอกสารนี้พูดถึงอะไร",
        "อธิบายรายงาน writing report", "หาไฟล์นโยบายมหาวิทยาลัย", "ดูข้อมูลจากไฟล์ที่เลือก",
    ]
    items.extend((question, "document_qa") for question in document_questions)

    program_questions = [
        "what are the admission requirements for Computer Science", "tuition fee for Business Administration",
        "list university programs", "which faculty offers Law", "program requirements for Data Science",
        "what is the language of the International Relations program", "how do I apply to Marketing",
        "ค่าเทอมคณะบริหารธุรกิจ", "เงื่อนไขสมัคร Computer Science", "มีคณะอะไรบ้าง",
        "หลักสูตร Law ใช้ภาษาอะไร", "คุณสมบัติการสมัคร Data Science", "ค่าเรียนต่อเทอมเท่าไร",
    ]
    items.extend((question, "program_data") for question in program_questions)

    greetings = [
        "hello", "hi", "good morning", "good afternoon", "hey there", "สวัสดี", "หวัดดี", "ดีครับ", "ดีค่ะ",
        "hello university assistant", "hi AI", "good evening",
    ]
    items.extend((question, "greeting") for question in greetings)

    out_of_scope_questions = [
        "help me write an IELTS essay", "translate this sentence into Thai", "explain photosynthesis",
        "what is the weather today", "write Python code for a calculator", "give me a study plan",
        "solve this equation", "what is the capital of France", "make this text professional",
        "help me prepare for an interview", "explain machine learning", "write a birthday message",
        "ช่วยแก้แกรมมาร์ประโยคนี้", "สอนคณิตศาสตร์ข้อนี้", "แปลภาษาอังกฤษเป็นไทย",
        "ช่วยเขียนข้อความให้สุภาพ", "อธิบายเรื่อง neural network", "วันนี้อากาศเป็นอย่างไร",
        "ช่วยวางแผนอ่านหนังสือ", "ทำโจทย์ SAT ให้หน่อย",
    ]
    items.extend((question, "out_of_scope") for question in out_of_scope_questions)
    return _unique_examples(items)


def _intent_from_label(label: Any) -> Optional[str]:
    if not isinstance(label, dict):
        return None
    raw = str(label.get("intent") or "").strip().lower()
    if raw in ALLOWED_INTENTS:
        return raw
    domain = str(label.get("domain") or "").strip().lower()
    mapping = {
        "student": "student_data", "students": "student_data", "grades": "student_data",
        "advisor": "advisor_data", "advisors": "advisor_data", "documents": "document_qa",
        "document": "document_qa", "program": "program_data", "programs": "program_data",
        "general": "out_of_scope", "normal_chat": "out_of_scope", "greeting": "greeting",
    }
    return mapping.get(domain)


def _intent_from_learning_domain(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw in ALLOWED_INTENTS:
        return raw
    if any(token in raw for token in ["student", "grade", "gpa", "score", "attendance", "scholar"]):
        return "student_data"
    if any(token in raw for token in ["advisor", "teacher", "lecturer"]):
        return "advisor_data"
    if any(token in raw for token in ["document", "pdf", "file", "excel", "upload"]):
        return "document_qa"
    if any(token in raw for token in ["program", "admission", "tuition", "faculty"]):
        return "program_data"
    return None


def load_training_examples(conn=None) -> List[Dict[str, str]]:
    """Combine curated examples with published, review-approved local corrections only."""
    own_conn = conn is None
    conn = conn or get_connection()
    examples: List[Dict[str, str]] = list(curated_training_examples())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT question, label, source
                FROM ai_router_training_examples
                WHERE is_active = TRUE
                ORDER BY created_at DESC
                LIMIT 2000
                """
            )
            for row in cur.fetchall():
                intent = _intent_from_label(row.get("label"))
                question = str(row.get("question") or "").strip()
                if question and intent:
                    examples.append({"question": question, "intent": intent, "source": str(row.get("source") or "router_example")})

            cur.execute(
                """
                SELECT original_question, corrected_question, learned_domain
                FROM ai_learning_memories
                WHERE is_active = TRUE AND review_status = 'published'
                ORDER BY updated_at DESC
                LIMIT 1000
                """
            )
            for row in cur.fetchall():
                intent = _intent_from_learning_domain(row.get("learned_domain"))
                question = str(row.get("corrected_question") or row.get("original_question") or "").strip()
                if question and intent:
                    examples.append({"question": question, "intent": intent, "source": "published_learning_memory"})
    except Exception:
        # The curated dataset is still sufficient for an initial model on a new install.
        pass
    finally:
        if own_conn:
            conn.close()
    return _unique_examples((item["question"], item["intent"]) for item in examples)


def examples_fingerprint(examples: List[Dict[str, str]]) -> str:
    payload = [{"q": " ".join(row["question"].lower().split()), "i": row["intent"]} for row in examples]
    payload.sort(key=lambda item: (item["i"], item["q"]))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _make_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "vectorizer",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 3),
                    min_df=1,
                    max_features=512,
                    sublinear_tf=True,
                    lowercase=True,
                ),
            ),
            (
                "mlp",
                MLPClassifier(
                    hidden_layer_sizes=(16,),
                    activation="relu",
                    solver="adam",
                    alpha=0.001,
                    batch_size=32,
                    learning_rate_init=0.01,
                    early_stopping=True,
                    validation_fraction=0.15,
                    n_iter_no_change=8,
                    max_iter=80,
                    random_state=42,
                ),
            ),
        ]
    )


def train_model_from_examples(examples: List[Dict[str, str]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Train and return a real neural classifier artifact plus quality metrics."""
    normalized = _unique_examples((row.get("question", ""), row.get("intent", "")) for row in examples)
    if len(normalized) < 30:
        raise ValueError("At least 30 labeled examples are required to train the neural router.")
    texts = [row["question"] for row in normalized]
    labels = [row["intent"] for row in normalized]
    counts = Counter(labels)
    if len(counts) < 2:
        raise ValueError("At least two intent labels are required to train the neural router.")

    can_split = min(counts.values()) >= 5 and len(texts) >= 60
    if can_split:
        x_train, x_test, y_train, y_test = train_test_split(
            texts,
            labels,
            test_size=0.22,
            random_state=42,
            stratify=labels,
        )
        evaluation_model = _make_pipeline()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            evaluation_model.fit(x_train, y_train)
        predictions = evaluation_model.predict(x_test)
        validation_accuracy = round(float(accuracy_score(y_test, predictions)), 4)
        validation_macro_f1 = round(float(f1_score(y_test, predictions, average="macro")), 4)
        validation_count = len(y_test)
    else:
        validation_accuracy = None
        validation_macro_f1 = None
        validation_count = 0

    model = _make_pipeline()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(texts, labels)

    artifact = {
        "model": model,
        "model_name": MODEL_NAME,
        "model_type": MODEL_TYPE,
        "schema_version": 1,
        "trained_at": _now(),
        "classes": sorted(set(labels)),
    }
    metrics = {
        "training_examples": len(texts),
        "class_distribution": dict(sorted(counts.items())),
        "validation_examples": validation_count,
        "validation_accuracy": validation_accuracy,
        "validation_macro_f1": validation_macro_f1,
        "algorithm": "TF-IDF character n-grams + MLPClassifier(hidden_layers=[16], solver=adam, early_stopping=true)",
        "uses_private_student_records": False,
    }
    return artifact, metrics


def _serialize_artifact(artifact: Dict[str, Any]) -> bytes:
    buffer = BytesIO()
    joblib.dump(artifact, buffer, compress=3)
    return buffer.getvalue()


def _deserialize_artifact(payload: bytes) -> Dict[str, Any]:
    return joblib.load(BytesIO(bytes(payload)))


def _fetch_registry_row(conn) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT model_name, model_type, model_version, artifact, metrics, training_examples,
                   class_labels, data_fingerprint, is_active, trained_at, updated_at
            FROM ai_model_registry
            WHERE model_name = %s AND is_active = TRUE
            LIMIT 1
            """,
            (MODEL_NAME,),
        )
        return cur.fetchone()


def get_neural_model_status() -> Dict[str, Any]:
    try:
        conn = get_connection()
        try:
            row = _fetch_registry_row(conn)
        finally:
            conn.close()
    except Exception as exc:
        return {
            "success": False,
            "model_name": MODEL_NAME,
            "available": False,
            "message": "Neural router status is unavailable until PostgreSQL initialization completes.",
            "error": str(exc)[:180],
        }
    if not row:
        return {
            "success": True,
            "model_name": MODEL_NAME,
            "available": False,
            "message": "No trained neural router artifact is stored yet.",
            "training_method": "supervised MLP classifier",
        }
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    classes = row.get("class_labels") if isinstance(row.get("class_labels"), list) else []
    return {
        "success": True,
        "model_name": MODEL_NAME,
        "available": True,
        "model_type": row.get("model_type"),
        "model_version": row.get("model_version"),
        "training_examples": int(row.get("training_examples") or 0),
        "class_labels": classes,
        "metrics": metrics,
        "trained_at": row.get("trained_at").isoformat() if row.get("trained_at") else None,
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
        "training_method": "supervised MLP classifier",
        "privacy_note": "Only curated examples and admin-published corrections are used. Student records are not used as model training text.",
    }


def train_neural_intent_model(*, force: bool = False, trigger_source: str = "manual") -> Dict[str, Any]:
    """Train, evaluate, and persist the local neural router in PostgreSQL."""
    conn = get_connection()
    try:
        examples = load_training_examples(conn)
        fingerprint = examples_fingerprint(examples)
        existing = _fetch_registry_row(conn)
        if existing and not force and str(existing.get("data_fingerprint") or "") == fingerprint:
            status = get_neural_model_status()
            return {
                "success": True,
                "status": "skipped_unchanged",
                "message": "The neural router already matches the approved training data.",
                "model": status,
            }

        artifact, metrics = train_model_from_examples(examples)
        version = f"{MODEL_VERSION_PREFIX}-{fingerprint[:12]}"
        payload = _serialize_artifact(artifact)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_model_registry (
                    model_name, model_type, model_version, artifact, metrics, training_examples,
                    class_labels, data_fingerprint, is_active, trained_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (model_name)
                DO UPDATE SET
                    model_type = EXCLUDED.model_type,
                    model_version = EXCLUDED.model_version,
                    artifact = EXCLUDED.artifact,
                    metrics = EXCLUDED.metrics,
                    training_examples = EXCLUDED.training_examples,
                    class_labels = EXCLUDED.class_labels,
                    data_fingerprint = EXCLUDED.data_fingerprint,
                    is_active = TRUE,
                    trained_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    MODEL_NAME,
                    MODEL_TYPE,
                    version,
                    psycopg2_binary(payload),
                    json.dumps(metrics),
                    metrics["training_examples"],
                    json.dumps(artifact["classes"]),
                    fingerprint,
                ),
            )
        conn.commit()
        _MODEL_CACHE.update({"cache_key": version, "model": artifact, "metadata": {"model_version": version, "metrics": metrics}})
        return {
            "success": True,
            "status": "trained",
            "trigger_source": trigger_source,
            "model_name": MODEL_NAME,
            "model_version": version,
            "metrics": metrics,
            "message": "A real supervised neural routing model was trained and stored locally.",
        }
    finally:
        conn.close()


def psycopg2_binary(payload: bytes):
    """Late import keeps pure model tests free from DB-driver coupling."""
    from psycopg2 import Binary
    return Binary(payload)


def _load_model() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    try:
        conn = get_connection()
        try:
            row = _fetch_registry_row(conn)
        finally:
            conn.close()
    except Exception:
        return None, None
    if not row or not row.get("artifact"):
        return None, None
    version = str(row.get("model_version") or "")
    if _MODEL_CACHE.get("cache_key") == version and _MODEL_CACHE.get("model"):
        return _MODEL_CACHE["model"], _MODEL_CACHE.get("metadata") or {}
    try:
        artifact = _deserialize_artifact(row.get("artifact"))
        metadata = {
            "model_version": version,
            "trained_at": row.get("trained_at").isoformat() if row.get("trained_at") else None,
            "metrics": row.get("metrics") if isinstance(row.get("metrics"), dict) else {},
        }
        _MODEL_CACHE.update({"cache_key": version, "model": artifact, "metadata": metadata})
        return artifact, metadata
    except Exception:
        return None, None


def predict_neural_intent(question: str) -> Dict[str, Any]:
    """Return a non-authoritative intent hint from the stored neural model."""
    text = " ".join(str(question or "").split()).strip()
    if not text:
        return {"available": False, "reason": "empty_question"}
    artifact, metadata = _load_model()
    if not artifact:
        return {"available": False, "reason": "model_not_trained"}
    try:
        model: Pipeline = artifact["model"]
        probabilities = model.predict_proba([text])[0]
        classes = list(model.classes_)
        best_index = max(range(len(probabilities)), key=lambda index: float(probabilities[index]))
        intent = str(classes[best_index])
        confidence = round(float(probabilities[best_index]), 4)
        if intent not in ALLOWED_INTENTS:
            return {"available": False, "reason": "invalid_model_label"}
        return {
            "available": True,
            "intent": intent,
            "confidence": confidence,
            "model_name": MODEL_NAME,
            "model_version": (metadata or {}).get("model_version"),
            "authoritative": False,
        }
    except Exception:
        return {"available": False, "reason": "prediction_failed"}
