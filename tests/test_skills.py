import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_explore_data_skill_writes_inventory(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    output = tmp_path / "inventory.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "templates"
                / "skills"
                / "explore-data-analysis"
                / "scripts"
                / "explore.py"
            ),
            str(data),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["samples"][0]["columns"] == ["a", "b"]


def test_autodl_skill_help_does_not_call_api():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates" / "skills" / "autodl" / "scripts" / "autodl.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "create" in completed.stdout
    assert "release" in completed.stdout
