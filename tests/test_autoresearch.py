from __future__ import annotations

import json
from pathlib import Path

import pytest

from medai.pipeline_state import PipelineState


@pytest.mark.parametrize("version", range(1, 6))
def test_legacy_base_manifest_is_rejected_without_writeback(
    tmp_path: Path, version: int
) -> None:
    base = tmp_path / f"base-{version}"
    base.mkdir()
    manifest = base / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"version": version, "inputs": {}, "stages": {}, "status": "completed"}
        ),
        encoding="utf-8",
    )
    before = manifest.read_bytes()
    with pytest.raises(RuntimeError, match="Auto Research base"):
        PipelineState(base)
    assert manifest.read_bytes() == before
