from __future__ import annotations

import runpy
from pathlib import Path

from flask import Flask

import assettrack.db as db


def test_runtime_entrypoint_does_not_enable_flask_debug(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    def fake_run(self: Flask, *args: object, **kwargs: object) -> None:
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(Flask, "run", fake_run)

    runpy.run_module("assettrack.intake.app", run_name="__main__")

    assert calls == [
        {
            "args": (),
            "kwargs": {"host": "0.0.0.0", "port": 8000, "debug": False},
        }
    ]
