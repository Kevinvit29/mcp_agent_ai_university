"""V29.2 regression checks for database-backed administrator credentials."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_admin_password_hash_is_salted_and_verifiable(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    from app.admin_accounts import hash_password, verify_password

    first = hash_password("admin123")
    second = hash_password("admin123")
    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password("admin123", first) is True
    assert verify_password("not-the-password", first) is False


def test_admin_password_minimum_is_enforced(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    from app.admin_accounts import validate_password

    with pytest.raises(ValueError):
        validate_password("short")


def test_v29_2_uses_database_accounts_not_runtime_env_login():
    auth = (ROOT / "backend" / "app" / "auth.py").read_text()
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    init_sql = (ROOT / "database" / "postgres-init.sql").read_text()
    frontend = (ROOT / "frontend" / "src" / "App.jsx").read_text()

    assert "authenticate_admin(user_id, password)" in auth
    assert "bootstrap_admin_account()" in main
    assert "CREATE TABLE IF NOT EXISTS admin_accounts" in init_sql
    assert "administrator account" in frontend.lower()
    assert "ADMIN_PASSWORD: ${ADMIN_PASSWORD" not in compose
    assert "name: university_ai" in compose
    assert "university_ai_postgres_data" in compose
