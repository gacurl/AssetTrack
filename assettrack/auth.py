# assettrack/auth.py
from __future__ import annotations

from functools import wraps

from flask import g, jsonify, request, session

from assettrack.users import ALLOWED_ROLES, get_user_by_id


def _forbidden_response():
    if request.path.startswith("/admin/") or request.is_json:
        return {"ok": False, "error": "Forbidden"}, 403
    return jsonify({"ok": False, "error": "Forbidden"}), 403


def current_user() -> dict | None:
    if hasattr(g, "current_user"):
        return g.current_user

    user_id = session.get("user_id")
    user = get_user_by_id(user_id)
    if user is None:
        session.pop("user_id", None)
        g.current_user = None
        return None

    role = str(user.get("role") or "").strip().lower()
    active = int(user.get("active") or 0) == 1
    if role not in ALLOWED_ROLES or not active:
        session.pop("user_id", None)
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
