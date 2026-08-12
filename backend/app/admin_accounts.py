"""Database-backed administrator account management.

Administrator credentials are stored as PBKDF2 password hashes in PostgreSQL.
Environment variables are used only once, to bootstrap the very first account
when the database has no administrator yet. After that, changing folders or an
`.env` file cannot change or invalidate an existing admin password.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from typing import Any, Dict, List, Optional

from app.production_security import is_production


def _connection():
    # Delayed import keeps password-hash utilities independently testable and
    # avoids establishing any PostgreSQL dependency until a database operation.
    from app.db.postgres import get_connection
    return get_connection()


PBKDF2_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH_DEVELOPMENT = 8
MIN_PASSWORD_LENGTH_PRODUCTION = 12


def _normalise_username(value: str) -> str:
    return str(value or "").strip()


def _password_min_length() -> int:
    return MIN_PASSWORD_LENGTH_PRODUCTION if is_production() else MIN_PASSWORD_LENGTH_DEVELOPMENT


def validate_password(password: str) -> None:
    candidate = str(password or "")
    if len(candidate) < _password_min_length():
        raise ValueError(f"Password must contain at least {_password_min_length()} characters.")
    if len(candidate) > 1024:
        raise ValueError("Password is too long.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_urlsafe(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        salt,
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_text, salt, encoded_digest = str(encoded).split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if not 100_000 <= iterations <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        expected = base64.b64decode(encoded_digest.encode("ascii"), validate=True)
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _public_account(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "admin_id": row["admin_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "is_active": bool(row["is_active"]),
        "password_changed_at": row.get("password_changed_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _bootstrap_values() -> tuple[str, str, str]:
    username = _normalise_username(
        os.getenv("ADMIN_BOOTSTRAP_USERNAME")
        or os.getenv("ADMIN_USERNAME")
        or "ADMIN"
    )
    display_name = _normalise_username(os.getenv("ADMIN_BOOTSTRAP_DISPLAY_NAME") or "Administrator")
    password = str(
        os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
        or os.getenv("ADMIN_PASSWORD")
        or ("" if is_production() else "admin123")
    )
    return username, display_name, password


def bootstrap_admin_account() -> Dict[str, Any]:
    """Create an initial admin only if the PostgreSQL account table is empty.

    The old ADMIN_PASSWORD variable is accepted only for this one-time migration
    path. It is never read by normal admin sign-in after the first account exists.
    """
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM admin_accounts")
            existing_count = int((cur.fetchone() or {}).get("count") or 0)
            if existing_count:
                cur.execute(
                    """
                    SELECT admin_id, username, display_name, is_active,
                           password_changed_at, created_at, updated_at
                    FROM admin_accounts
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
                return {"created": False, "account": _public_account(cur.fetchone())}

            username, display_name, password = _bootstrap_values()
            if not username:
                raise RuntimeError("ADMIN_BOOTSTRAP_USERNAME must be configured before the first administrator is created.")
            if not password:
                raise RuntimeError("ADMIN_BOOTSTRAP_PASSWORD must be configured before the first administrator is created.")
            validate_password(password)
            admin_id = "ADM-" + uuid.uuid4().hex[:12].upper()
            cur.execute(
                """
                INSERT INTO admin_accounts
                    (admin_id, username, display_name, password_hash, is_active, created_by)
                VALUES (%s, %s, %s, %s, TRUE, 'bootstrap')
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                (admin_id, username, display_name, hash_password(password)),
            )
            row = cur.fetchone()
            conn.commit()
            return {"created": True, "account": _public_account(row)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def authenticate_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    candidate = _normalise_username(username)
    if not candidate:
        return None
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, password_hash, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                WHERE lower(username) = lower(%s)
                LIMIT 1
                """,
                (candidate,),
            )
            account = cur.fetchone()
            if not account or not account.get("is_active"):
                return None
            if not verify_password(password, str(account.get("password_hash") or "")):
                return None
            return _public_account(account)
    finally:
        conn.close()


def lookup_admin_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Return a safe account view for local recovery/status checks."""
    candidate = _normalise_username(username)
    if not candidate:
        return None
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                WHERE lower(username) = lower(%s)
                LIMIT 1
                """,
                (candidate,),
            )
            return _public_account(cur.fetchone())
    finally:
        conn.close()


def local_recover_admin(*, username: str, new_password: Optional[str], ensure_active: bool = True) -> Dict[str, Any]:
    """Explicit local-container recovery; not used by normal web requests.

    It can reactivate an existing account and, only when a new password is
    supplied interactively, replace the PBKDF2 hash. Plaintext credentials are
    never stored in .env or returned from this function.
    """
    candidate = _normalise_username(username)
    if not candidate:
        raise ValueError("Administrator username is required.")
    if new_password is not None:
        validate_password(new_password)
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, password_hash, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                WHERE lower(username) = lower(%s)
                FOR UPDATE
                """,
                (candidate,),
            )
            account = cur.fetchone()
            if not account:
                raise ValueError("Administrator account was not found.")

            updates = []
            params = []
            if new_password is not None:
                updates.extend(["password_hash = %s", "password_changed_at = CURRENT_TIMESTAMP"])
                params.append(hash_password(new_password))
            if ensure_active:
                updates.append("is_active = TRUE")
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(account["admin_id"])
            cur.execute(
                f"""
                UPDATE admin_accounts
                SET {", ".join(updates)}
                WHERE admin_id = %s
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                tuple(params),
            )
            row = cur.fetchone()
            conn.commit()
            return _public_account(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_admin_account(admin_id: str) -> Optional[Dict[str, Any]]:
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                WHERE admin_id = %s
                LIMIT 1
                """,
                (str(admin_id or "").strip(),),
            )
            return _public_account(cur.fetchone())
    finally:
        conn.close()


def list_admin_accounts() -> List[Dict[str, Any]]:
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                ORDER BY created_at ASC, username ASC
                """
            )
            return [_public_account(row) for row in cur.fetchall()]
    finally:
        conn.close()


def create_admin_account(*, username: str, display_name: str, password: str, created_by: str) -> Dict[str, Any]:
    username = _normalise_username(username)
    display_name = _normalise_username(display_name) or username
    if not username or len(username) > 80:
        raise ValueError("Administrator username must contain 1–80 characters.")
    if len(display_name) > 255:
        raise ValueError("Administrator display name is too long.")
    validate_password(password)
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM admin_accounts WHERE lower(username) = lower(%s) LIMIT 1",
                (username,),
            )
            if cur.fetchone():
                raise ValueError("An administrator with that username already exists.")
            admin_id = "ADM-" + uuid.uuid4().hex[:12].upper()
            cur.execute(
                """
                INSERT INTO admin_accounts
                    (admin_id, username, display_name, password_hash, is_active, created_by)
                VALUES (%s, %s, %s, %s, TRUE, %s)
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                (admin_id, username, display_name, hash_password(password), str(created_by or "ADMIN")),
            )
            row = cur.fetchone()
            conn.commit()
            return _public_account(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def change_admin_password(*, admin_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
    validate_password(new_password)
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT admin_id, username, display_name, password_hash, is_active,
                       password_changed_at, created_at, updated_at
                FROM admin_accounts
                WHERE admin_id = %s
                FOR UPDATE
                """,
                (str(admin_id or "").strip(),),
            )
            account = cur.fetchone()
            if not account or not account.get("is_active"):
                raise ValueError("Administrator account is not available.")
            if not verify_password(current_password, str(account.get("password_hash") or "")):
                raise ValueError("Current password is incorrect.")
            cur.execute(
                """
                UPDATE admin_accounts
                SET password_hash = %s,
                    password_changed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE admin_id = %s
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                (hash_password(new_password), account["admin_id"]),
            )
            row = cur.fetchone()
            conn.commit()
            return _public_account(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_admin_password(*, username: str, new_password: str) -> Dict[str, Any]:
    """Break-glass local recovery utility used only by the explicit CLI script."""
    validate_password(new_password)
    candidate = _normalise_username(username)
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE admin_accounts
                SET password_hash = %s,
                    password_changed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE lower(username) = lower(%s)
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                (hash_password(new_password), candidate),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Administrator account was not found.")
            conn.commit()
            return _public_account(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_admin_active(*, target_admin_id: str, active: bool, actor_admin_id: str) -> Dict[str, Any]:
    if str(target_admin_id) == str(actor_admin_id) and not active:
        raise ValueError("You cannot disable the administrator account currently signed in.")
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM admin_accounts WHERE is_active = TRUE")
            active_count = int((cur.fetchone() or {}).get("count") or 0)
            if not active and active_count <= 1:
                raise ValueError("At least one active administrator account is required.")
            cur.execute(
                """
                UPDATE admin_accounts
                SET is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE admin_id = %s
                RETURNING admin_id, username, display_name, is_active,
                          password_changed_at, created_at, updated_at
                """,
                (bool(active), str(target_admin_id or "").strip()),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Administrator account was not found.")
            conn.commit()
            return _public_account(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
