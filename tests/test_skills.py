import gzip
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from medai.models import DataInventory

ROOT = Path(__file__).parents[1]
SKILL_ROOT = ROOT / "templates" / "skills" / "explore-data"


def run_adapter(
    adapter_name: str,
    data: Path,
    output: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "adapter" / adapter_name),
            str(data),
            "--output",
            str(output),
            *arguments,
        ],
        capture_output=True,
        text=True,
    )


def load_adapter_module(adapter_name: str):
    path = SKILL_ROOT / "adapter" / adapter_name
    spec = importlib.util.spec_from_file_location(adapter_name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mimic_adapter_writes_bounded_actual_rows(tmp_path: Path):
    metadata = json.loads(
        (SKILL_ROOT / "metadata" / "mimic-iv.json").read_text(encoding="utf-8")
    )
    admissions = next(
        item
        for item in metadata["files"]
        if item["name"] == "admissions.csv.gz"
    )
    data = tmp_path / "raw"
    table = data / "hosp" / "admissions.csv.gz"
    table.parent.mkdir(parents=True)
    columns = admissions["info"]["columns"]
    first = {column: f"{column}-value" for column in columns}
    first["admission_type"] = "x" * 20
    second = {column: f"{column}-second" for column in columns}
    with gzip.open(table, "wt", encoding="utf-8", newline="") as handle:
        import csv

        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows([first, second])

    output = tmp_path / "inventory.json"
    completed = run_adapter(
        "mimic-iv_adapter.py",
        data,
        output,
        "--file",
        "hosp/admissions.csv.gz",
        "--rows",
        "1",
        "--max-field-chars",
        "8",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    DataInventory.model_validate(payload)
    assert payload["dataset"]["id"] == "mimic-iv"
    explored = payload["explored_files"][0]
    assert explored["structure"]["columns"] == columns
    assert explored["sample"]["rows_returned"] == 1
    assert explored["sample"]["rows"][0]["subject_id"] == "subject_"
    assert explored["sample"]["fields_truncated"] is True
    assert payload["scan"]["truncated"] is False


def test_mimic_metadata_is_compact_and_matches_local_headers_when_available():
    metadata = json.loads(
        (SKILL_ROOT / "metadata" / "mimic-iv.json").read_text(encoding="utf-8")
    )
    assert set(metadata) == {"dataset_id", "files"}
    assert metadata["dataset_id"] == "mimic-iv"
    assert len(metadata["files"]) == 34
    for item in metadata["files"]:
        assert set(item) == {"directory", "name", "format", "compression", "info"}
        assert set(item["info"]) <= {"columns"}

    local_raw = ROOT / "resources" / "datasets" / "mimic-iv" / "raw"
    if not local_raw.is_dir():
        return
    import csv

    for item in metadata["files"]:
        path = local_raw / item["directory"] / item["name"]
        assert path.is_file(), path
        if item["format"] == "csv":
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                assert next(csv.reader(handle)) == item["info"]["columns"]


def test_adapters_expose_the_common_class_interface(tmp_path: Path):
    data = tmp_path / "raw"
    data.mkdir()
    for adapter_name in ("mimic-iv_adapter.py", "generic_adapter.py"):
        module = load_adapter_module(adapter_name)
        adapter = module.DatasetAdapter(data)
        for method in (
            "list_resources",
            "sample",
            "build_inventory",
            "write_inventory",
        ):
            assert callable(getattr(adapter, method))


def test_generic_adapter_samples_safe_formats_and_blocks_unsafe_loads(tmp_path: Path):
    data = tmp_path / "raw"
    data.mkdir()
    (data / "sample.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (data / "sample.json").write_text('{"cohort": [1, 2]}', encoding="utf-8")
    with gzip.open(data / "notes.txt.gz", "wt", encoding="utf-8") as handle:
        handle.write("first\nsecond\n")
    with zipfile.ZipFile(data / "bundle.zip", "w") as archive:
        archive.writestr("inside.txt", "do not extract")
    (data / "opaque.bin").write_bytes(b"\x00\x01\x02\xff")
    (data / "unsafe.pkl").write_bytes(b"not-a-real-pickle")

    output = tmp_path / "inventory.json"
    completed = run_adapter("generic_adapter.py", data, output)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    DataInventory.model_validate(payload)
    explored = {item["path"]: item for item in payload["explored_files"]}
    assert explored["sample.csv"]["structure"]["columns"] == ["a", "b"]
    assert explored["sample.csv"]["sample"]["rows"][0] == {"a": "1", "b": "2"}
    assert explored["sample.json"]["sample"]["value"] == {"cohort": [1, 2]}
    assert explored["notes.txt.gz"]["sample"]["lines"] == ["first", "second"]
    assert explored["bundle.zip"]["structure"]["extracted"] is False
    assert explored["bundle.zip"]["sample"]["members"][0]["name"] == "inside.txt"
    assert not (data / "inside.txt").exists()
    assert explored["opaque.bin"]["structure"]["kind"] == "binary"
    assert explored["opaque.bin"]["sample"]["prefix_hex"] == "000102ff"
    assert "may execute code" in explored["unsafe.pkl"]["error"]


def test_generic_adapter_marks_scan_truncation(tmp_path: Path):
    data = tmp_path / "raw"
    data.mkdir()
    for index in range(3):
        (data / f"{index}.txt").write_text(str(index), encoding="utf-8")
    output = tmp_path / "inventory.json"
    completed = run_adapter(
        "generic_adapter.py",
        data,
        output,
        "--max-files",
        "2",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scan"]["files_scanned"] == 2
    assert payload["scan"]["truncated"] is True
    assert any("stopped after 2 files" in warning for warning in payload["warnings"])


def test_generic_adapter_rejects_paths_outside_raw_root(tmp_path: Path):
    data = tmp_path / "raw"
    data.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("a\n1\n", encoding="utf-8")
    module = load_adapter_module("generic_adapter.py")
    adapter = module.DatasetAdapter(data)
    with pytest.raises(ValueError, match="escapes the raw root"):
        adapter.sample("../outside.csv")

    with pytest.raises(ValueError, match="must not be inside"):
        adapter.write_inventory(data / "inventory.json", selected_files=[])


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
