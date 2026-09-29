import hmac
import os
import secrets
import time
from collections import defaultdict
from fastapi import HTTPException, Request
from .config import DATA_DIR

def session_secret():
    value = os.getenv("GRANTIQ_SECRET_KEY", "")
    if os.getenv("GRANTIQ_ADMIN_PASSWORD"):
        if len(value) < 32:
            raise RuntimeError("Set GRANTIQ_SECRET_KEY to a random secret of at least 32 characters before enabling shared access.")
        return value
    if value:
        return value
    path = DATA_DIR / ".session-secret"
    if not path.exists():
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_text(encoding="utf-8").strip()

def csrf_token(request: Request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]

def validate_csrf(request: Request, form):
    expected, supplied = request.session.get("csrf", ""), str(form.get("csrf_token", ""))
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "The form expired. Reload the page and try again.")

login_attempts = defaultdict(list)
def check_login_limit(request):
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    login_attempts[key] = [t for t in login_attempts[key] if now-t < 300]
    if len(login_attempts[key]) >= 10:
        raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
    login_attempts[key].append(now)
