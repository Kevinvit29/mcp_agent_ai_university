"""V18 static regression checks that require no database or Gemini key."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_local_embedding_is_free_default(monkeypatch):
    monkeypatch.setenv("NEURAL_EMBEDDING_PROVIDER", "local")
    from app.agent.neural_embedding import configured_embedding_provider, embed_text
    assert configured_embedding_provider() == "local"
    vector = embed_text("how many students study law", provider="local")
    assert len(vector) == 384
    assert any(value != 0 for value in vector)


def test_auto_training_controller_exists():
    code = (ROOT / "backend" / "app" / "agent" / "auto_training.py").read_text()
    assert "run_local_training_now" in code
    assert "uses_gemini_tokens" in code
    assert "incremental" in code.lower()


def test_frontend_uses_local_training_endpoint():
    code = (ROOT / "frontend" / "src" / "App.jsx").read_text()
    assert "/ai/training/run-local" in code
    assert "Train with Gemini embeddings" not in code
