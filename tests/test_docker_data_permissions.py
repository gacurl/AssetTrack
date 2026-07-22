from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_pins_assettrack_runtime_user_ids() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "addgroup -S -g 101 assettrack" in dockerfile
    assert "adduser -S -u 100 -G assettrack" in dockerfile
    assert "USER assettrack" in dockerfile


def test_compose_initializes_bind_mount_before_non_root_app_start() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "assettrack-data-init:" in compose
    assert 'user: "0:0"' in compose
    assert "chown 100:101 /app/data" in compose
    assert "chmod 0750 /app/data" in compose
    assert "condition: service_completed_successfully" in compose
    assert "- ./data:/app/data" in compose


def test_compose_does_not_make_persistent_data_world_writable() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "chmod 0777" not in compose
    assert "chmod 777" not in compose
