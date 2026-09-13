#!/usr/bin/env python3
"""One local control command for the V30 Docker application.

This script never deletes Docker volumes. It intentionally uses only Python's
standard library and the Docker Compose CLI already required by the project.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SERVICES = ("postgres", "mongo", "mcp_server", "backend", "frontend")


def _run(
    command: List[str],
    *,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=check,
    )


def _compose(*arguments: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "compose", *arguments], capture=capture, check=check)


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is not installed. Install and start Docker Desktop first.")
    result = _run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker Desktop is not running. Start it and wait for the engine to become ready.")
    compose = _compose("version", capture=True, check=False)
    if compose.returncode != 0:
        raise RuntimeError("Docker Compose is unavailable. Update Docker Desktop and try again.")


def _ensure_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        return
    example = ROOT / ".env.example"
    if not example.exists():
        raise RuntimeError("Both .env and .env.example are missing.")
    shutil.copy2(example, env_path)
    print("Created .env from .env.example.")


def _parse_compose_rows(raw: str) -> List[Dict[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            return [value]
    except json.JSONDecodeError:
        pass

    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _service_status() -> Dict[str, Dict[str, str]]:
    result = _compose("ps", "-a", "--format", "json", capture=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Could not inspect Docker services.").strip())

    status: Dict[str, Dict[str, str]] = {}
    for row in _parse_compose_rows(result.stdout):
        service = str(row.get("Service") or row.get("service") or "").strip()
        if not service:
            continue
        state = str(row.get("State") or row.get("state") or "").strip().lower()
        health = str(row.get("Health") or row.get("health") or "").strip().lower()
        status_text = str(row.get("Status") or row.get("status") or "").strip()
        if not health and "(healthy)" in status_text.lower():
            health = "healthy"
        status[service] = {
            "state": state,
            "health": health,
            "status": status_text,
        }
    return status


def show_status() -> bool:
    _require_docker()
    rows = _service_status()
    healthy = 0
    print("\nV30 services")
    print("-" * 68)
    for service in EXPECTED_SERVICES:
        row = rows.get(service)
        if not row:
            print(f"{service:12} missing")
            continue
        state = row["state"] or "unknown"
        health = row["health"] or ("running" if state == "running" else "not healthy")
        ok = state == "running" and health in {"healthy", "running"}
        healthy += int(ok)
        print(f"{service:12} {state:10} {health}")
    print("-" * 68)
    print(f"Healthy services: {healthy}/{len(EXPECTED_SERVICES)}")
    return healthy == len(EXPECTED_SERVICES)


def _bootstrap_status() -> None:
    print("\nDataset synchronization")
    _compose("exec", "-T", "backend", "python", "-m", "app.system_bootstrap", "--status")


def _application_check() -> bool:
    code = (
        "import json; "
        "from app.main import run_admin_system_check; "
        "result=run_admin_system_check('admin'); "
        "print(json.dumps(result, indent=2, default=str)); "
        "raise SystemExit(0 if result.get('success') else 1)"
    )
    result = _compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        code,
        check=False,
    )
    return result.returncode == 0


def _container_release_tests() -> bool:
    print("\nBackend compile and regression tests")
    compile_result = _compose(
        "exec", "-T", "backend", "python", "-m", "compileall", "-q",
        "app", "mcp_server/app",
        check=False,
    )
    if compile_result.returncode != 0:
        return False
    test_result = _compose(
        "exec", "-T", "backend", "python", "-m", "pytest", "-q", "tests",
        check=False,
    )
    if test_result.returncode != 0:
        return False
    print("\nLive role/database answer gates")
    for module in (
        "app.agent.academic_brain_gate",
        "app.agent.random_question_gate",
    ):
        gate_result = _compose(
            "exec", "-T", "backend", "python", "-m", module,
            check=False,
        )
        if gate_result.returncode != 0:
            return False
    print("\nSigned four-role live API matrix")
    role_result = _compose(
        "exec", "-T", "backend", "python", "scripts/check_roles_live.py",
        check=False,
    )
    if role_result.returncode != 0:
        return False
    return True


def start() -> int:
    _require_docker()
    _ensure_env()
    _compose("config", "--quiet")
    print("Building and starting V30. Existing database volumes are preserved.")
    _compose("up", "-d", "--build", "--wait", "--wait-timeout", "360")
    services_ok = show_status()
    if services_ok:
        _bootstrap_status()
        print("\nV30 is ready: http://localhost:3100")
        return 0
    print("\nOne or more services are not healthy. Run: python3 scripts/v30_control.py doctor")
    return 1


def check() -> int:
    _require_docker()
    services_ok = show_status()
    if not services_ok:
        return 1
    _bootstrap_status()
    print("\nApplication checks")
    checks_ok = _application_check()
    print("\nSystem check passed." if checks_ok else "\nSystem check needs attention. Review the failed check above.")
    return 0 if checks_ok else 1


def doctor() -> int:
    _require_docker()
    _ensure_env()
    config = _compose("config", "--quiet", check=False)
    print("Compose configuration:", "valid" if config.returncode == 0 else "invalid")
    if config.returncode != 0:
        return config.returncode
    result = check()
    if result != 0:
        print("\nRecent backend and MCP logs")
        _compose("logs", "--tail", "100", "backend", "mcp_server", "postgres", "mongo", check=False)
    return result


def logs(services: Iterable[str]) -> int:
    _require_docker()
    selected = list(services) or list(EXPECTED_SERVICES)
    return _compose("logs", "--tail", "160", *selected, check=False).returncode


def stop() -> int:
    _require_docker()
    print("Stopping V30 containers. Database volumes are preserved.")
    return _compose("stop", check=False).returncode


def restart() -> int:
    _require_docker()
    print("Recreating V30 containers. Database volumes are preserved.")
    result = _compose("down", "--remove-orphans", check=False)
    if result.returncode != 0:
        return result.returncode
    return start()


def release() -> int:
    """Build the exact source, run every local gate, and leave V30 running."""
    start_result = start()
    if start_result != 0:
        return start_result
    if not _container_release_tests():
        print("\nRelease blocked by compile or regression test failure.")
        return 1
    print("\nVerifying the production frontend build")
    frontend_result = _compose("build", "frontend", check=False)
    if frontend_result.returncode != 0:
        print("\nRelease blocked by frontend build failure.")
        return frontend_result.returncode
    final_result = check()
    if final_result == 0:
        print("\nV30 release gate passed. Create and verify a backup before deployment.")
    return final_result


def backup() -> int:
    _require_docker()
    _ensure_env()
    return _run(["bash", str(ROOT / "scripts" / "backup.sh")], check=False).returncode


def verify_backup(archive: str) -> int:
    candidate = Path(archive).expanduser().resolve()
    if not candidate.is_file():
        print(f"Backup archive not found: {candidate}", file=sys.stderr)
        return 1
    return _run(
        ["bash", str(ROOT / "scripts" / "verify_backup.sh"), str(candidate)],
        check=False,
    ).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start, inspect, and diagnose the V30 University AI stack without deleting database volumes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="Build, start, wait for all five services, and verify dataset status.")
    subparsers.add_parser("status", help="Show an exact five-service health summary.")
    subparsers.add_parser("check", help="Run service, dataset, and five-part application checks.")
    subparsers.add_parser("doctor", help="Run checks and print relevant logs when something fails.")
    log_parser = subparsers.add_parser("logs", help="Show recent logs; optionally name services.")
    log_parser.add_argument("services", nargs="*", choices=EXPECTED_SERVICES)
    subparsers.add_parser("restart", help="Safely recreate containers without deleting volumes.")
    subparsers.add_parser("stop", help="Stop containers without deleting them or their volumes.")
    subparsers.add_parser("release", help="Build V30 and run compile, regression, frontend, four-role, AI, and database gates.")
    subparsers.add_parser("backup", help="Create a checksummed PostgreSQL and MongoDB backup archive.")
    verify_parser = subparsers.add_parser("verify-backup", help="Verify a backup archive without changing a database.")
    verify_parser.add_argument("archive")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "start":
            return start()
        if args.command == "status":
            return 0 if show_status() else 1
        if args.command == "check":
            return check()
        if args.command == "doctor":
            return doctor()
        if args.command == "logs":
            return logs(args.services)
        if args.command == "restart":
            return restart()
        if args.command == "stop":
            return stop()
        if args.command == "release":
            return release()
        if args.command == "backup":
            return backup()
        if args.command == "verify-backup":
            return verify_backup(args.archive)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\nV30 control error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
