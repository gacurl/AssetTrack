# assettrack/auth.py
from __future__ import annotations

from functools import wraps
from pathlib import Path
import time

from flask import g, render_template, request, session

from assettrack.users import ALLOWED_ROLES, get_user_by_id

SESSION_IDLE_TIMEOUT_SECONDS = 20 * 60
SESSION_ABSOLUTE_TIMEOUT_SECONDS = 60 * 60
AUTH_SESSION_KEYS = ("user_id", "last_seen", "session_started_at")


def now_seconds() -> int:
    return int(time.time())


def begin_auth_session(user_id: int) -> None:
    started_at = now_seconds()
    session["user_id"] = int(user_id)
    session["last_seen"] = started_at
    session["session_started_at"] = started_at


def _clear_pending_asset_import_session() -> None:
    pending = session.pop("pending_asset_import", None)
    if not isinstance(pending, dict):
        return
    temp_path_value = str(pending.get("temp_path") or "").strip()
    if temp_path_value:
        Path(temp_path_value).unlink(missing_ok=True)


def clear_auth_session() -> None:
    _clear_pending_asset_import_session()
    for key in AUTH_SESSION_KEYS:
        session.pop(key, None)


def _session_timing_valid() -> bool:
    try:
        last_seen = int(session["last_seen"])
        session_started_at = int(session["session_started_at"])
    except (KeyError, TypeError, ValueError):
        return False

    current = now_seconds()
    if current - last_seen > SESSION_IDLE_TIMEOUT_SECONDS:
        return False
    if current - session_started_at > SESSION_ABSOLUTE_TIMEOUT_SECONDS:
        return False
    return True


def _prefers_json_response() -> bool:
    if request.is_json:
        return True

    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes["application/json"] >= request.accept_mimetypes["text/html"]
    )


def _forbidden_response():
    if _prefers_json_response():
        return {"ok": False, "error": "Forbidden"}, 403
    return render_template("403.html"), 403


def current_user() -> dict | None:
    if hasattr(g, "current_user"):
        return g.current_user

    user_id = session.get("user_id")
    if user_id is not None and not _session_timing_valid():
        clear_auth_session()
        g.current_user = None
        return None

    user = get_user_by_id(user_id)
    if user is None:
        clear_auth_session()
        g.current_user = None
        return None

    role = str(user.get("role") or "").strip().lower()
    active = int(user.get("active") or 0) == 1
    if role not in ALLOWED_ROLES or not active:
        clear_auth_session()
        g.current_user = None
        return None

    g.current_user = user
    return user


def require_login(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return _forbidden_response()
        return view_func(*args, **kwargs)

    return wrapped


def require_role(required_role: str):
    normalized_required = str(required_role or "").strip().lower()

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return _forbidden_response()

            role = str(user.get("role") or "").strip().lower()
            if role not in ALLOWED_ROLES or role != normalized_required:
                return _forbidden_response()
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
