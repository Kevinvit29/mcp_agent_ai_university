"""V30 regression checks: supervised local model + safe 1,000-row synthetic dataset."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_v30_dataset_is_large_linked_and_explicitly_synthetic():
    from app.demo_data import DATA_ORIGIN, DEMO_PASSWORD, build_demo_dataset

    dataset = build_demo_dataset(1000)
    assert DATA_ORIGIN == "synthetic_demo_v30"
    assert DEMO_PASSWORD == "demo1234"
    assert len(dataset["students"]) == 1000
    assert len(dataset["advisors"]) == 40
    assert len(dataset["programs"]) == 12
    assert len(dataset["courses"]) == 96
    assert len(dataset["enrollments"]) == 6000
    assert len(dataset["assessments"]) == 24000
    assert dataset["students"][0]["student_id"] == "S001"
    assert dataset["students"][-1]["student_id"] == "S1000"
    assert len({row["student_id"] for row in dataset["students"]}) == 1000
    assert all(row["data_origin"] == DATA_ORIGIN for row in dataset["students"])
    assert all(row["email"].endswith("@demo-university.example") for row in dataset["students"])
    assert all(row["student_id"].startswith("S") for row in dataset["enrollments"])


def test_v30_neural_router_is_a_real_trainable_mlp_model():
    from app.agent.neural_intent_trainer import curated_training_examples, train_model_from_examples

    examples = curated_training_examples()
    artifact, metrics = train_model_from_examples(examples)
    model = artifact["model"]
    assert "mlp" in model.named_steps
    assert metrics["training_examples"] >= 100
    assert metrics["validation_examples"] > 0
    assert metrics["validation_accuracy"] is not None
    assert metrics["uses_private_student_records"] is False
    assert artifact["model_type"] == "tfidf_char_ngram_mlp_classifier"
    assert set(artifact["classes"]) >= {"student_data", "document_qa", "program_data"}


def test_v30_packaging_has_explicit_safety_guards_and_ui_controls():
    seed_code = (ROOT / "backend" / "app" / "synthetic_seed.py").read_text()
    docs = (ROOT / "docs" / "V30_CLEAN_FOUNDATION.md").read_text()
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    frontend = (ROOT / "frontend" / "src" / "App.jsx").read_text()
    planner = (ROOT / "backend" / "app" / "agent" / "query_planner_ai.py").read_text()

    assert "APP_ENV" in seed_code and "production" in seed_code
    assert "--confirm-synthetic-demo" in seed_code
    assert "--replace-v28-demo" in seed_code
    assert "does not fine-tune Gemini/OpenAI" in docs
    assert "/ai/training/neural-router/run" in main
    assert "Train AI router" not in frontend
    assert "/ai/training/neural-router/run" not in frontend
    assert "query_academic_records" in planner
    assert r"S\d{3,6}" in planner
