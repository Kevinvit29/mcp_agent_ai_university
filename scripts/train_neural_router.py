#!/usr/bin/env python3
"""Manually train or refresh the V30 local supervised neural router."""
from __future__ import annotations
import json
from app.db.postgres import init_postgres_tables
from app.agent.neural_intent_trainer import train_neural_intent_model

init_postgres_tables()
print(json.dumps(train_neural_intent_model(force=True, trigger_source="script"), indent=2, default=str))
