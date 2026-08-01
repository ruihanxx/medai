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
