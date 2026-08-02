import os
import shutil
import subprocess
from pathlib import Path


def prepare_launcher(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    project_root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "medai"
    shutil.copy2(project_root / "medai", launcher)
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    model_cache = tmp_path / "model-cache"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$MEDAI_TEST_DOCKER_LOG"
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
    printf 'sha256:test-image\\n'
elif [[ "${1:-}" == "run" ]]; then
    mkdir -p "$MEDAI_TEST_MODEL_CACHE"
    printf '%s\\n' '{"models-dir":{"pipeline":"/opt/medai-models/pipeline","vlm":"/opt/medai-models/vlm"}}' > "$MEDAI_TEST_MODEL_CACHE/mineru.json"
fi
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["MEDAI_MODEL_CACHE"] = str(model_cache)
    env["MEDAI_TEST_DOCKER_LOG"] = str(docker_log)
    env["MEDAI_TEST_MODEL_CACHE"] = str(model_cache)
    return launcher, env, docker_log, model_cache


def test_init_builds_image_and_initializes_reusable_models(tmp_path: Path):
    launcher, env, docker_log, model_cache = prepare_launcher(tmp_path)

    initialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert initialized.returncode == 0, initialized.stderr
    assert (model_cache / "mineru.json").is_file()
    assert (model_cache / ".medai-image-id").read_text(encoding="utf-8").strip() == (
        "sha256:test-image"
    )
    init_calls = docker_log.read_text(encoding="utf-8")
    assert "build --platform linux/amd64" in init_calls
    assert "--entrypoint mineru-models-download" in init_calls
    assert "--model_type all" in init_calls

    docker_log.write_text("", encoding="utf-8")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    run = subprocess.run(
        [str(launcher), "--paper", str(paper), "--provider", "codex"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stderr
    run_calls = docker_log.read_text(encoding="utf-8")
    assert "build " not in run_calls
    assert "MINERU_MODEL_SOURCE=local" in run_calls
    assert f"src={model_cache},dst=/opt/medai-models,readonly" in run_calls


def test_run_requires_successful_init(tmp_path: Path):
    launcher, env, docker_log, _ = prepare_launcher(tmp_path)
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    run = subprocess.run(
        [str(launcher), "--paper", str(paper), "--provider", "codex"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 2
    assert "run ./medai init first" in run.stderr
    assert "run " not in docker_log.read_text(encoding="utf-8")
