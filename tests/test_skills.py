import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_autodl_skill_help_does_not_call_api():
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "templates"
                / "skills"
                / "computation_provider"
                / "scripts"
                / "autodl.py"
            ),
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "create" in completed.stdout
    assert "release" in completed.stdout
    create_help = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "templates"
                / "skills"
                / "computation_provider"
                / "scripts"
                / "autodl.py"
            ),
            "create",
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert create_help.returncode == 0
    assert "--image-uuid" in create_help.stdout


def test_autodl_skill_rejects_gpu_outside_the_pro_pool_before_api_access(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "templates"
                / "skills"
                / "computation_provider"
                / "scripts"
                / "autodl.py"
            ),
            "create",
            "--gpu-spec",
            "not-in-pro-pool",
            "--state",
            str(tmp_path / "instance.json"),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "test-token",
            "AUTODL_IMAGE_UUID": "base-image-l2t43iu6uk",
        },
    )
    assert completed.returncode != 0
    assert "Unsupported AutoDL Pro GPU specification" in completed.stderr
