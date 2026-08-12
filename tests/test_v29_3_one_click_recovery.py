"""Release checks for V30 Windows startup and local Admin recovery."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_port_is_configurable_and_not_hardcoded():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '${FRONTEND_PORT:-3100}:8080' in compose


def test_recovery_module_uses_database_and_hidden_prompt():
    recovery = (ROOT / "backend" / "app" / "admin_recovery.py").read_text()
    assert 'getpass.getpass' in recovery
    assert 'local_recover_admin' in recovery
    assert 'bootstrap_admin_account()' in recovery
    assert 'ADMIN_PASSWORD' not in recovery


def test_legacy_reset_script_repairs_python_import_path():
    script = (ROOT / "scripts" / "reset_admin_password.py").read_text()
    assert 'app.admin_recovery' in script
    assert 'sys.path.insert(0, str(ROOT))' in script


def test_windows_repair_never_removes_volumes_and_opens_actual_port():
    script = (ROOT / "scripts" / "start-v30.ps1").read_text()
    assert 'docker compose down --remove-orphans' in script
    assert 'down -v' not in script
    assert 'Find-FreeLocalPort' in script
    assert 'app.admin_recovery' in script
    assert 'http://localhost:$actualPort' in script


def test_clickable_recovery_launcher_is_present():
    launcher = (ROOT / "RESET_ADMIN_AND_START.bat").read_text()
    assert 'RECOVER_ADMIN_V30.bat' in launcher
    assert 'RECOVER_ADMIN_V30.bat' in launcher
