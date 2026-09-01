import json
from pathlib import Path

import pytest

from medai.pipeline_state import MANIFEST_VERSION, PipelineState


@pytest.mark.parametrize("version", range(1, MANIFEST_VERSION))
def test_legacy_state_is_read_only(tmp_path: Path, version: int):
    output = tmp_path / "output"
    output.mkdir()
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": version,
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "running",
                "inputs": {"paper": "/workspace/inputs/paper.pdf", "provider": "codex"},
                "current_stage": "preprocess_pdf",
                "stages": {
                    "preflight": {"status": "completed"},
                    "preprocess_pdf": {"status": "running"},
                },
            }
        ),
        encoding="utf-8",
    )

    before = manifest_path.read_bytes()
    with pytest.raises(RuntimeError, match="read-only.*new output directory"):
        PipelineState(output)
    assert manifest_path.read_bytes() == before


def test_stage_retry_preserves_checkpoints_and_counts_attempts(tmp_path: Path):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})
    state.start_stage("report_agents")
    state.update_stage_checkpoints("report_agents", {"completed_claims": ["C1"]})
    state.fail("interrupted")

    resumed = PipelineState(state.output)
    resumed.resume({"provider": "codex"})
    resumed.start_stage("report_agents")

    assert resumed.get_stage_checkpoints("report_agents") == {
        "completed_claims": ["C1"]
    }
    assert resumed.state["stages"]["report_agents"]["attempts"] == 2


def test_invalidation_can_preserve_explicit_infrastructure_checkpoints(
    tmp_path: Path,
):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})
    state.start_stage("codegen_agent")
    state.update_stage_checkpoints("codegen_agent", {"source_prepared": True})
    state.complete_stage("codegen_agent", ["codebase"])

    state.invalidate_stages(
        ["codegen_agent"],
        "replacement instance",
        checkpoint_overrides={
            "codegen_agent": {
                "source_prepared": True,
                "infrastructure_resume": True,
            }
        },
    )

    assert state.get_stage_status("codegen_agent") == "invalidated"
    assert state.get_stage_checkpoints("codegen_agent") == {
        "source_prepared": True,
        "infrastructure_resume": True,
    }


def test_cleanup_warning_preserves_completed_status(tmp_path: Path):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})
    state.mark_completed()

    state.record_cleanup_warning("release", "provider unavailable")

    manifest = PipelineState(state.output).state
    assert manifest["status"] == "completed"
    assert manifest["cleanup_warning"]["operation"] == "release"
    assert manifest["cleanup_warning"]["error"] == "provider unavailable"
    assert manifest["cleanup_warning"]["recorded_at"]


def test_completed_stage_checkpoints_can_be_migrated(tmp_path: Path):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})
    state.start_stage("data_availability_agent")
    state.update_stage_checkpoints(
        "data_availability_agent", {"scope_sha256": "old", "verdict": "UNKNOWN"}
    )
    state.complete_stage("data_availability_agent", ["execution_scope.json"])

    state.migrate_completed_stage_checkpoints(
        "data_availability_agent", {"scope_sha256": "new", "verdict": "PARTIAL"}
    )

    assert state.get_stage_checkpoints("data_availability_agent") == {
        "scope_sha256": "new",
        "verdict": "PARTIAL",
    }


def test_resume_cannot_enable_force_remote_on_an_existing_run(tmp_path: Path):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})

    with pytest.raises(RuntimeError, match="force_remote"):
        state.resume({"provider": "codex", "force_remote": True})
