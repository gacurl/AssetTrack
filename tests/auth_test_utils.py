# tests/auth_test_utils.py
from __future__ import annotations

import assettrack.auth as auth
from assettrack.users import create_user

def create_test_user(
    *,
    username: str,
    password: str,
    role: str,
    active: bool = True,
) -> int:
    created = create_user(username=username, password=password, role=role, active=active)
    return int(created["id"])


def login_session(client, user_id: int) -> None:
    current_time = auth.now_seconds()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["last_seen"] = current_time
        sess["session_started_at"] = current_time
