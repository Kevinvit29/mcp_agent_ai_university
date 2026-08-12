"""V18 automatic zero-token training/index refresh controller.

The controller polls source fingerprints for existing Mongo/PostgreSQL tables and
uploaded files. It rebuilds only sources whose fingerprint changed, using the
local vectorizer (no Gemini embedding/API calls). It also refreshes a small
centroid routing helper and reports the persisted supervised neural router.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db.postgres import get_latest_training_job, run_local_auto_training_cycle

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_state: Dict[str, Any] = {
    "enabled": False,
    "running": False,
    "interval_seconds": 300,
    "provider": "local",
    "last_result": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() not in {"0", "false", "no", "off"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _interval() -> int:
    try:
        return max(60, min(int(os.getenv("AUTO_TRAINING_INTERVAL_SECONDS", "300")), 86400))
    except Exception:
        return 300


def run_local_training_now(*, mongo_uri: str, mongo_db_name: str, trigger_source: str = "manual") -> Dict[str, Any]:
    """Run one safe local-only incremental index refresh."""
    if not _lock.acquire(blocking=False):
        return {
            "success": True,
            "status": "already_running",
            "message": "Local auto-training is already running. No duplicate job was started.",
            "latest": get_auto_training_status(),
        }
    try:
        _state.update({"running": True, "last_started_at": _now(), "last_error": None})
        result = run_local_auto_training_cycle(
            mongo_uri=mongo_uri,
            mongo_db_name=mongo_db_name,
            trigger_source=trigger_source,
        )
        _state["last_result"] = result
        if not result.get("success"):
            _state["last_error"] = result.get("error") or "; ".join(result.get("errors") or [])
        return result
    except Exception as exc:  # defensive guard: training must never crash chat
        _state["last_error"] = str(exc)
        return {"success": False, "provider": "local", "error": str(exc)}
    finally:
        _state.update({"running": False, "last_finished_at": _now()})
        _lock.release()


def _loop(mongo_uri: str, mongo_db_name: str) -> None:
    # Run once after startup so legacy files/tables get an agent; after that the
    # job is incremental and skips unchanged sources.
    run_local_training_now(mongo_uri=mongo_uri, mongo_db_name=mongo_db_name, trigger_source="startup")
    while not _stop_event.wait(_interval()):
        run_local_training_now(mongo_uri=mongo_uri, mongo_db_name=mongo_db_name, trigger_source="scheduled")


def start_auto_training_loop(*, mongo_uri: str, mongo_db_name: str) -> Dict[str, Any]:
    global _thread
    enabled = _truthy(os.getenv("AUTO_TRAINING_ENABLED", "true"))
    _state.update({"enabled": enabled, "interval_seconds": _interval(), "provider": "local"})
    if not enabled:
        return get_auto_training_status()
    if _thread and _thread.is_alive():
        return get_auto_training_status()
    _stop_event.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(mongo_uri, mongo_db_name),
        name="university-local-auto-training",
        daemon=True,
    )
    _thread.start()
    return get_auto_training_status()


def stop_auto_training_loop() -> None:
    _stop_event.set()


def get_auto_training_status() -> Dict[str, Any]:
    result = dict(_state)
    try:
        latest = get_latest_training_job()
    except Exception as exc:
        latest = {"error": str(exc)}
    result["latest_job"] = latest
    result["method"] = "incremental_local_semantic_index_centroid_and_neural_router"
    result["uses_gemini_tokens"] = False
    result["note"] = (
        "This automatically rebuilds changed table/file indexes with local vectors and keeps "
        "a small supervised neural routing model current. It does not fine-tune a generative LLM."
    )
    try:
        from app.agent.neural_intent_trainer import get_neural_model_status
        result["neural_router"] = get_neural_model_status()
    except Exception:
        result["neural_router"] = {"available": False, "message": "Neural router status unavailable."}
    return result
