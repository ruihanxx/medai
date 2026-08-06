import json
from pathlib import Path

import pytest

from medai.pipeline_state import MANIFEST_VERSION, PipelineState


def test_version_one_state_resumes_and_rejects_changed_inputs(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
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

    state = PipelineState(output)
    state.resume(
        {
            "paper": "/workspace/inputs/paper.pdf",
            "paper_sha256": "abc",
            "provider": "codex",
        }
    )

    resumed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert resumed["version"] == MANIFEST_VERSION
    assert resumed["resume_count"] == 1
    assert resumed["current_stage"] is None
    assert resumed["inputs"]["paper_sha256"] == "abc"
    assert state.is_stage_completed("preflight")

    before_mismatch = manifest_path.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="provider"):
        PipelineState(output).resume(
            {
                "paper": "/workspace/inputs/paper.pdf",
                "paper_sha256": "abc",
                "provider": "claude",
            }
        )
    assert manifest_path.read_text(encoding="utf-8") == before_mismatch


def test_stage_retry_preserves_checkpoints_and_counts_attempts(tmp_path: Path):
    state = PipelineState.create(tmp_path / "output", {"provider": "codex"})
    state.start_stage("report_agents")
    state.update_stage_checkpoints("report_agents", {"completed_experiments": ["E1"]})
    state.fail("interrupted")

    resumed = PipelineState(state.output)
    resumed.resume({"provider": "codex"})
    resumed.start_stage("report_agents")

    assert resumed.get_stage_checkpoints("report_agents") == {
        "completed_experiments": ["E1"]
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
