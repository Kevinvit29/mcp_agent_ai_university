"""V30 integrity checks for reliable startup and synchronized demo data."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_v30_has_one_bootstrap_owner_for_synthetic_demo_data():
    mongo_init = (ROOT / "database" / "mongo-init.js").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    bootstrap = (ROOT / "backend" / "app" / "system_bootstrap.py").read_text()

    assert "does not install a second 100-record" in mongo_init
    assert "for (let i = 4; i <= 100; i++)" not in mongo_init
    assert "python -m app.system_bootstrap --ensure-synthetic" in compose
    assert "EXPECTED_STUDENT_COUNT = 1000" in bootstrap
    assert "count_documents" in bootstrap
    assert "student_profiles" in bootstrap


def test_v30_bootstrap_refuses_production_and_unrecognised_data():
    bootstrap = (ROOT / "backend" / "app" / "system_bootstrap.py").read_text()
    assert "Synthetic data bootstrap is disabled in production." in bootstrap
    assert "DEMO_DATA_MODE" in bootstrap
    assert "Refusing to replace or mix unknown records." in bootstrap
    assert "LEGACY_DEMO_ORIGINS" in bootstrap


def test_v30_windows_launcher_uses_one_click_health_and_status_flow():
    launcher = (ROOT / "scripts" / "start-v30.ps1").read_text()
    assert "Find-FreeLocalPort" in launcher
    assert "$desiredPort = 3100" in launcher
    assert "python -m app.system_bootstrap --status" in launcher
    assert "docker compose down --remove-orphans" in launcher
    assert "down -v" not in launcher
    recovery = (ROOT / "RECOVER_ADMIN_V30.bat").read_text()
    assert "start-v30.ps1" in recovery
    assert "-ResetAdmin" in recovery


def test_v30_frontend_uses_same_origin_api_and_truthful_demo_credentials():
    app = (ROOT / "frontend" / "src" / "LoginPage.jsx").read_text()
    env = (ROOT / "frontend" / ".env.example").read_text()
    assert "VITE_API_BASE_URL=/api" in env
    assert "demo1234" in app
    assert "1234567890123" not in app
    assert "RECOVER_ADMIN_V30.bat" in app


def test_v30_cli_wrapper_has_stable_import_root():
    script = (ROOT / "scripts" / "seed_synthetic_university_data.py").read_text()
    assert "from app.synthetic_seed import main" in script
    assert "sys.path.insert(0, str(ROOT))" in script


def test_v30_production_rejects_demo_seed_and_default_bootstrap_password(monkeypatch):
    from app.production_security import production_configuration_errors

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("MCP_INTERNAL_KEY", "y" * 48)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://university.example")
    monkeypatch.setenv("ALLOW_LEGACY_DEMO_PASSWORDS", "false")
    monkeypatch.setenv("DEMO_DATA_MODE", "true")
    monkeypatch.setenv("AUTO_SEED_SYNTHETIC_DATA", "true")
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "admin123")
    errors = production_configuration_errors()
    assert any("DEMO_DATA_MODE" in error for error in errors)
    assert any("AUTO_SEED_SYNTHETIC_DATA" in error for error in errors)
    assert any("default demo password" in error for error in errors)
