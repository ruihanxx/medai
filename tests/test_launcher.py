import json
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
    dataset_root = tmp_path / "datasets"
    (dataset_root / "test-data").mkdir(parents=True)
    run = subprocess.run(
        [
            str(launcher),
            "--replicate",
            "--paper",
            str(paper),
            "--data",
            "test-data",
            "--dataset-path",
            str(dataset_root),
            "--provider",
            "codex",
        ],
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
    assert f"src={dataset_root / 'test-data'},dst=/workspace/data,readonly" in run_calls
    assert "--data /workspace/data" in run_calls


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
    dataset_root = tmp_path / "datasets"
    (dataset_root / "test-data").mkdir(parents=True)

    run = subprocess.run(
        [
            str(launcher),
            "--replicate",
            "--paper",
            str(paper),
            "--data",
            "test-data",
            "--dataset-path",
            str(dataset_root),
            "--provider",
            "codex",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 2
    assert "run medai init first" in run.stderr
    assert command_log.read_text(encoding="utf-8") == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
def test_replicate_requires_at_least_one_explicit_dataset_source(tmp_path: Path):
    launcher, env, _, _ = prepare_launcher(tmp_path)
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()

    cases = [
        (
            ["--data", "dataset-a"],
            "requires --dataset-path, --clouddrive, or both",
        ),
        (
            ["--data", "dataset-a", "--dataset-path", str(dataset_root)],
            "Local dataset directory does not exist",
        ),
        (
            ["--data", str(dataset_root), "--dataset-path", str(dataset_root)],
            "--data as one safe dataset name",
        ),
    ]
    for arguments, error in cases:
        completed = subprocess.run(
            [str(launcher), "--replicate", "--paper", str(paper), *arguments],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 2
        assert error in completed.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
def test_autoresearch_mounts_base_read_only_and_skips_mineru(tmp_path: Path):
    launcher, env, command_log, _ = prepare_launcher(tmp_path)
    initialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr

    base_run = tmp_path / "runs" / "base"
    base_run.mkdir(parents=True)
    (base_run / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "inputs": {
                    "provider": "codex",
                    "clouddrive": True,
                    "computation_provider": "vastai",
                    "drive_provider": "google-drive",
                    "cloud_dataset": "mimic-iv",
                    "cloud_source": "medai/mimic-iv",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    command_log.write_text("", encoding="utf-8")

    run = subprocess.run(
        [str(launcher), "--autoresearch", "--replicate-run", str(base_run)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stderr
    calls = command_log.read_text(encoding="utf-8")
    campaign_001 = base_run / "autoresearch" / "campaign_001"
    assert "mineru -p" not in calls
    assert f"src={base_run},dst=/workspace/base-run,readonly" in calls
    assert f"src={campaign_001},dst=/workspace/autoresearch" in calls
    assert "--autoresearch --replicate-run /workspace/base-run" in calls
    assert "--assessment-threshold 0.0" in calls
    assert "dst=/workspace/data" not in calls

    (campaign_001 / "manifest.json").write_text("{}\n", encoding="utf-8")
    resumed = subprocess.run(
        [
            str(launcher),
            "--autoresearch",
            "--replicate-run",
            str(base_run),
            "--output",
            str(campaign_001),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert f"Resuming Auto Research output: {campaign_001}" in resumed.stdout

    next_campaign = subprocess.run(
        [str(launcher), "--autoresearch", "--replicate-run", str(base_run)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert next_campaign.returncode == 0, next_campaign.stderr
    campaign_002 = base_run / "autoresearch" / "campaign_002"
    assert campaign_002.is_dir()
    assert f"Auto Research output: {campaign_002}" in next_campaign.stdout

    invalid_output = subprocess.run(
        [
            str(launcher),
            "--autoresearch",
            "--replicate-run",
            str(base_run),
            "--output",
            str(base_run),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid_output.returncode == 2
    assert "separate from the read-only base run" in invalid_output.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper integration test")
def test_cloud_drive_datasets_are_not_mounted_from_host(tmp_path: Path):
    launcher, env, command_log, _ = prepare_launcher(tmp_path)
    initialized = subprocess.run(
        [str(launcher), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    command_log.write_text("", encoding="utf-8")

    run = subprocess.run(
        [
            str(launcher),
            "--replicate",
            "--paper",
            str(paper),
            "--clouddrive",
            "--data",
            "mimic-iv",
            "--data",
            "eicu",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stderr
    calls = command_log.read_text(encoding="utf-8")
    assert "--clouddrive --data mimic-iv --data eicu" in calls
    assert "dst=/workspace/data" not in calls

    dataset_root = tmp_path / "datasets"
    local_dataset = dataset_root / "mimic-iv"
    second_local_dataset = dataset_root / "eicu"
    local_dataset.mkdir(parents=True)
    second_local_dataset.mkdir()
    command_log.write_text("", encoding="utf-8")
    dual_source_run = subprocess.run(
        [
            str(launcher),
            "--replicate",
            "--paper",
            str(paper),
            "--data",
            "mimic-iv",
            "--data",
            "eicu",
            "--dataset-path",
            str(dataset_root),
            "--clouddrive",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert dual_source_run.returncode == 0, dual_source_run.stderr
    calls = command_log.read_text(encoding="utf-8")
    assert f"src={local_dataset},dst=/workspace/data/mimic-iv,readonly" in calls
    assert f"src={second_local_dataset},dst=/workspace/data/eicu,readonly" in calls
    assert (
        "--data /workspace/data/mimic-iv --dataset-name mimic-iv "
        "--data /workspace/data/eicu --dataset-name eicu --clouddrive "
        "--cloud-dataset mimic-iv --cloud-dataset eicu"
        in calls
    )
