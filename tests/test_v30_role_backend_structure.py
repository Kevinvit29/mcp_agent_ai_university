"""Regression checks for role-separated API and database boundaries."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_role_routes_are_separate_from_main_application():
    main = (ROOT / "backend" / "app" / "main.py").read_text()
    assert "create_admin_router(process_knowledge_file)" in main
    assert "create_advisor_router(process_knowledge_file)" in main
    assert "include_router(student_router)" in main
    assert '@app.get("/advisor/' not in main
    assert '@app.post("/advisor/' not in main
    assert '@app.get("/student/' not in main
    assert '@app.post("/student/' not in main


def test_each_role_has_an_explicit_database_interface():
    roles_dir = ROOT / "backend" / "app" / "roles"
    admin = (roles_dir / "admin" / "repository.py").read_text()
    advisor = (roles_dir / "advisor" / "repository.py").read_text()
    student = (roles_dir / "student" / "repository.py").read_text()

    assert "save_admin_document" in admin
    assert "set_admin_active" in admin
    assert "advisor_teaches_subject" in advisor
    assert "delete_advisor_document_for_advisor" in advisor
    assert "list_student_accessible_documents" in student
    assert "save_" not in student
    assert "delete_" not in student


def test_role_routers_use_signed_identity_not_request_role_parameters():
    roles_dir = ROOT / "backend" / "app" / "roles"
    for role in ("admin", "advisor", "student"):
        source = (roles_dir / role / "router.py").read_text()
        assert f'require_identity(request, "{role}")' in source
        assert "user_role:" not in source
        assert f"requester_{role}_id:" not in source
