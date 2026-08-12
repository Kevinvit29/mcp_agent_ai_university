from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def test_reports_are_proxied_through_frontend():
    nginx = (ROOT / "frontend" / "nginx.conf").read_text()
    assert "location /reports/" in nginx
    assert "location /document-views/" in nginx
    assert "proxy_pass http://backend:8000;" in nginx

def test_report_links_use_public_app_origin_not_private_backend():
    source = (ROOT / "backend" / "app" / "main.py").read_text()
    assert 'PUBLIC_APP_URL", "http://localhost:3100"' in source
    assert 'report["download_url"] = f"{public_app_url}{report[\'url\']}"' in source

def test_compose_keeps_backend_private_and_defines_public_app_url():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "PUBLIC_APP_URL: ${PUBLIC_APP_URL:-http://localhost:3100}" in compose
    backend = compose.split("  backend:\n", 1)[1].split("  frontend:\n", 1)[0]
    assert re.search(r"^\s{4}ports:\s*$", backend, flags=re.M) is None
