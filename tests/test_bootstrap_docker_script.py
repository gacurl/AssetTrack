from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def test_bootstrap_docker_script_starts_compose_without_host_permission_repair(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    source_script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_docker.sh"
    target_script = scripts_dir / "bootstrap_docker.sh"
    shutil.copy2(source_script, target_script)

    docker_bin_dir = tmp_path / "bin"
    docker_bin_dir.mkdir()
    docker_args_path = tmp_path / "docker-args.txt"
    docker_stub = docker_bin_dir / "docker"
    docker_stub.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > \"{docker_args_path}\"\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{docker_bin_dir}:{env['PATH']}"

    subprocess.run(
        [str(target_script)],
        cwd=repo_root,
        env=env,
        check=True,
    )

    data_dir = repo_root / "data"
    assert not data_dir.exists()
    assert docker_args_path.read_text(encoding="utf-8").splitlines() == ["compose", "up", "-d", "--build"]


def test_bootstrap_docker_script_does_not_apply_world_writable_permissions() -> None:
    source_script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_docker.sh"

    script_text = source_script.read_text(encoding="utf-8")

    assert "chmod 0777" not in script_text
    assert "chmod 777" not in script_text
