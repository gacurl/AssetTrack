# assettrack/transitions.py

from __future__ import annotations

from assettrack.audit import record_event
from assettrack.assets import update_asset


def transition_custody_state(
    conn,
    asset_tag: str,
    *,
    new_state: str,
    actor: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Choke point for custody_state transitions.
    Updates the asset and records an audit event together.
    """

    # 1) Apply the state change using the existing, sanitized update path
    update_asset(conn, asset_tag, custody_state=new_state)

    # 2) Record the audit event (append-only)
    record_event(
        conn,
        asset_tag=asset_tag,
        event_type="custody_state_changed",
        actor=actor,
        notes=notes,
        payload={"custody_state": new_state},
    )
