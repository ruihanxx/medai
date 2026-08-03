import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from medai.launcher import (
    PythonInfo,
    _native_homebrew_install_command,
    _python_supported,
    _runtime_commands,
)


def prepare_launcher(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    project_root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "medai"
    shutil.copy2(project_root / "medai", launcher)
    package = tmp_path / "src" / "medai"
    (package / "data").mkdir(parents=True)
    shutil.copy2(project_root / "src" / "medai" / "launcher.py", package / "launcher.py")
    shutil.copy2(
        project_root / "src" / "medai" / "data" / "mineru-requirements.txt",
        package / "data" / "mineru-requirements.txt",
    )
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    command_log.write_text("", encoding="utf-8")
    model_cache = tmp_path / "model-cache"

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\\n' "$*" >> "$MEDAI_TEST_COMMAND_LOG"
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
printf 'models-download %s\\n' "$*" >> "$MEDAI_TEST_COMMAND_LOG"
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
printf 'mineru %s\\n' "$*" >> "$MEDAI_TEST_COMMAND_LOG"
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

    host_architecture = "arm64" if sys.platform == "darwin" else platform.machine().casefold()
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
elif [[ "${1:-}" == "-c" && "${2:-}" == *"torch.cuda.is_available"* ]]; then
    printf 'cpu\\n'
elif [[ "${1:-}" == "-c" ]]; then
    printf '3.12:__HOST_ARCHITECTURE__\\n'
elif [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
    printf 'pip %s\\n' "$*" >> "$MEDAI_TEST_COMMAND_LOG"
else
    exit 2
fi
""".replace("__HOST_ARCHITECTURE__", host_architecture),
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["MEDAI_LAUNCHER_PYTHON"] = sys.executable
    env["MEDAI_MINERU_PYTHON"] = str(fake_python)
    env["MEDAI_MODEL_CACHE"] = str(model_cache)
    env["MEDAI_TEST_COMMAND_LOG"] = str(command_log)
    env["MEDAI_TEST_MODEL_CACHE"] = str(model_cache)
    env["MEDAI_TEST_FAKE_MINERU"] = str(fake_mineru)
    env["MEDAI_TEST_FAKE_MODELS_DOWNLOAD"] = str(fake_models_download)
    return launcher, env, command_log, model_cache


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
def test_init_builds_image_and_runs_cpu_mineru(tmp_path: Path):
    launcher, env, command_log, model_cache = prepare_launcher(tmp_path)

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
    init_calls = command_log.read_text(encoding="utf-8")
    assert "mineru-requirements.txt" in init_calls
    assert "docker build --platform linux/amd64" in init_calls
    assert "models-download --source auto --model_type all" in init_calls

    command_log.write_text("", encoding="utf-8")
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
    run_calls = command_log.read_text(encoding="utf-8")
    assert "docker build" not in run_calls
    assert "mineru -p" in run_calls
    assert "-b pipeline" in run_calls
    assert "MEDAI_MINERU_OUTPUT=/workspace/mineru-output" in run_calls
    assert "dst=/workspace/mineru-output,readonly" in run_calls


def test_python_and_virtualenv_platform_policy():
    executable = Path("python")
    assert _python_supported(PythonInfo(executable, 3, 12, "arm64"), "Darwin", True)
    assert not _python_supported(PythonInfo(executable, 3, 12, "x86_64"), "Darwin", True)
    assert not _python_supported(PythonInfo(executable, 3, 12, "x86_64"), "Darwin", False)
    assert _python_supported(PythonInfo(executable, 3, 12, "amd64"), "Windows", False)
    assert not _python_supported(PythonInfo(executable, 3, 13, "amd64"), "Windows", False)
    assert not _python_supported(PythonInfo(executable, 3, 12, "arm64"), "Windows", False)

    windows = _runtime_commands(Path(".venv"), system="Windows")
    assert windows.python == Path(".venv/Scripts/python.exe")
    assert windows.mineru == Path(".venv/Scripts/mineru.exe")
    assert windows.models_download == Path(".venv/Scripts/mineru-models-download.exe")


def test_native_homebrew_install_command_runs_as_arm64(tmp_path: Path):
    arch = tmp_path / "arch"
    arch.write_text("", encoding="utf-8")
    assert _native_homebrew_install_command(
        Path("/opt/homebrew/bin/brew"), arch
    ) == [
        str(arch),
        "-arm64",
        "/opt/homebrew/bin/brew",
        "install",
        "python@3.12",
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
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
    printf '3.11:stale\\n'
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
    archived = list(model_cache.glob(".venv.incompatible-3.11-stale*"))
    assert len(archived) == 1
    assert (model_cache / ".venv" / "bin" / "mineru").is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
def test_run_requires_successful_init(tmp_path: Path):
    launcher, env, command_log, _ = prepare_launcher(tmp_path)
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
    assert "run medai init first" in run.stderr
    assert command_log.read_text(encoding="utf-8") == ""
