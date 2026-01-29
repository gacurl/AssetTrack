# assettrack/transitions.py

def transition_asset_state(conn, asset_tag, *, new_state, actor=None, notes=None):
    """
    Single choke point for asset state transitions.
    Applies the update and records audit together.
    """
    raise NotImplementedError("State transition not implemented yet")
