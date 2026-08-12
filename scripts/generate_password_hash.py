#!/usr/bin/env python3
"""Print a PBKDF2-SHA256 password hash for student/advisor account migration."""
import base64
import getpass
import hashlib
import secrets

password = getpass.getpass("Password: ")
confirm = getpass.getpass("Confirm password: ")
if not password or password != confirm:
    raise SystemExit("Passwords did not match or were empty.")
salt = secrets.token_urlsafe(18)
iterations = 310_000
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
print(f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode()}")
