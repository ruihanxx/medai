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
    docker_log.write_text("", encoding="utf-8")
    model_cache = tmp_path / "model-cache"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$MEDAI_TEST_DOCKER_LOG"
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
    printf 'sha256:test-image\\n'
fi
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    fake_models_download = fake_bin / "mineru-models-download"
    fake_models_download.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'models-download %s\\n' "$*" >> "$MEDAI_TEST_DOCKER_LOG"
mkdir -p "$MEDAI_TEST_MODEL_CACHE"
printf '%s\\n' '{"models-dir":{"pipeline":"/host/pipeline","vlm":"/host/vlm"}}' > "$MINERU_TOOLS_CONFIG_JSON"
""",
        encoding="utf-8",
    )
    fake_models_download.chmod(0o755)

    fake_mineru = fake_bin / "mineru"
    fake_mineru.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'mineru %s\\n' "$*" >> "$MEDAI_TEST_DOCKER_LOG"
output=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then
        output="$2"
        break
    fi
    shift
done
mkdir -p "$output/paper/auto/images"
printf '# Paper\\n' > "$output/paper/auto/paper.md"
""",
        encoding="utf-8",
    )
    fake_mineru.chmod(0o755)

    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
    venv="$3"
    mkdir -p "$venv/bin"
    cp "$0" "$venv/bin/python"
    cp "$MEDAI_TEST_FAKE_MINERU" "$venv/bin/mineru"
    cp "$MEDAI_TEST_FAKE_MODELS_DOWNLOAD" "$venv/bin/mineru-models-download"
elif [[ "${1:-}" == "-c" ]]; then
    printf '3.12:x86_64\\n'
elif [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
    printf 'pip %s\\n' "$*" >> "$MEDAI_TEST_DOCKER_LOG"
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    fake_uname = fake_bin / "uname"
    fake_uname.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-s" ]]; then
    printf 'Linux\\n'
elif [[ "$1" == "-m" ]]; then
    printf 'x86_64\\n'
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    fake_uname.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["MEDAI_MODEL_CACHE"] = str(model_cache)
    env["MEDAI_TEST_DOCKER_LOG"] = str(docker_log)
    env["MEDAI_TEST_MODEL_CACHE"] = str(model_cache)
    env["MEDAI_TEST_FAKE_MINERU"] = str(fake_mineru)
    env["MEDAI_TEST_FAKE_MODELS_DOWNLOAD"] = str(fake_models_download)
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
    assert (model_cache / ".venv" / "bin" / "mineru").is_file()
    assert (model_cache / ".medai-image-id").read_text(encoding="utf-8").strip() == (
        "host-mineru:sha256:test-image"
    )
    init_calls = docker_log.read_text(encoding="utf-8")
    assert "pip -m pip install" in init_calls
    assert "mineru[pipeline]>=3,<4" in init_calls
    assert "build --platform linux/amd64" in init_calls
    assert "models-download --source auto --model_type all" in init_calls

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
    assert "mineru -p" in run_calls
    assert "MEDAI_MINERU_OUTPUT=/workspace/mineru-output" in run_calls
    assert "dst=/workspace/mineru-output,readonly" in run_calls
    assert f"src={model_cache},dst=/opt/medai-models,readonly" not in run_calls


def test_init_rejects_rosetta_python_on_apple_silicon(tmp_path: Path):
    launcher, env, docker_log, model_cache = prepare_launcher(tmp_path)
    env["MEDAI_MINERU_PYTHON"] = str(Path(env["PATH"].split(":", maxsplit=1)[0]) / "python3")
    fake_uname = Path(env["PATH"].split(":", maxsplit=1)[0]) / "uname"
    fake_uname.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-s" ]]; then
    printf 'Darwin\\n'
elif [[ "$1" == "-m" ]]; then
    printf 'x86_64\\n'
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    fake_uname.chmod(0o755)
    fake_sysctl = fake_uname.with_name("sysctl")
    fake_sysctl.write_text(
        """#!/usr/bin/env bash
if [[ "$*" == *"sysctl.proc_translated"* ]]; then
    printf '1\\n'
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    fake_sysctl.chmod(0o755)

    initialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert initialized.returncode == 2
    assert "native arm64 Python" in initialized.stderr
    assert not model_cache.exists()
    assert docker_log.read_text(encoding="utf-8") == ""


def test_init_archives_incompatible_host_environment(tmp_path: Path):
    launcher, env, _, model_cache = prepare_launcher(tmp_path)
    initialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr

    stale_python = model_cache / ".venv" / "bin" / "python"
    stale_python.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-c" ]]; then
    printf '3.11:x86_64\\n'
else
    exit 2
fi
""",
        encoding="utf-8",
    )
    stale_python.chmod(0o755)

    reinitialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert reinitialized.returncode == 0, reinitialized.stderr
    assert (model_cache / ".venv.incompatible-3.11-x86_64").is_dir()
    assert (model_cache / ".venv" / "bin" / "mineru").is_file()


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
