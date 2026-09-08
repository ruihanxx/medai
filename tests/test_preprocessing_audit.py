from __future__ import annotations

import json
from pathlib import Path

import pytest

from medai.prompts import TEMPLATES_DIR
from medai.workflow import read_audit_report


def test_audit_issue_has_one_origin_node_and_open_details(tmp_path) -> None:
    path = tmp_path / "audit.json"
    path.write_text(
        json.dumps(
            {
                "verdict": "FAIL",
                "issues": [
                    {
                        "node_id": "P_split_2",
                        "description": "test split cannot be reconstructed",
                        "route": "preprocessing_fix",
                        "editable_paths": ["src/split.py"],
                        "required_fix": {"inspect": "supplement"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = read_audit_report(path)
    assert report["issues"][0]["required_fix"] == {"inspect": "supplement"}


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "PASS", "issues": [{"node_id": "P1", "description": "x"}]},
        {"verdict": "FAIL", "issues": []},
        {"verdict": "FAIL", "issues": [{"node_id": "", "description": "x"}]},
        {"verdict": "FAIL", "issues": [{"node_id": "P1", "description": ""}]},
    ],
)
def test_audit_report_rejects_inconsistent_or_empty_issues(tmp_path, payload) -> None:
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        read_audit_report(path)


def test_cohort_refinement_forbids_paper_result_gates() -> None:
    prompt = (TEMPLATES_DIR / "cohort_refine" / "session_instructions.md").read_text(
        encoding="utf-8"
    )
    prompt = " ".join(prompt.split())
    assert "graph `paper_result` as an observed reference output" in prompt
    assert "runtime assertion, reconciliation gate" in prompt
    assert "Only source, method, schema, and artifact-integrity conditions" in prompt


def test_cohort_refinement_requires_candidate_semantic_delta_review() -> None:
    prompt = (TEMPLATES_DIR / "cohort_refine" / "session_instructions.md").read_text(
        encoding="utf-8"
    )
    prompt = " ".join(prompt.split())
    assert "The host already created the candidate" in prompt
    assert "self-audit the complete candidate delta against the read-only authoritative baseline" in prompt
    assert "Revert every unrelated delta" in prompt
    assert "If any extra effect contradicts that documented interpretation" in prompt
    assert "This coverage review never triggers failure exit" in prompt
    assert "exit nonzero" not in prompt


@pytest.mark.parametrize("mode", ["repair", "record_only", "interrupted_remote"])
def test_refinement_candidate_lifecycle(tmp_path: Path, monkeypatch, mode: str) -> None:
    from medai.artifacts import write_json
    from medai.config import RunConfig
    from medai.data_availability import sha256_file
    from medai.models import PaperGraph
    from medai.pipeline_state import PipelineState
    from medai.study_graph import load_node_state, merge_node_updates, write_empty_node_state
    from medai.workflow import cohort_refine_agent_node

    output = tmp_path / "run"
    config = RunConfig(paper=tmp_path / "paper.pdf", output=output, provider="codex")
    pipeline = PipelineState.create(output, {})
    graph = PaperGraph.model_validate({
        "datasets": [{"id": "D1", "inputs": [], "method": {}, "provenance": []}],
        "preprocessing": [{"id": "P1", "inputs": ["D1"], "method": {}, "provenance": []}],
        "training": [], "models": [],
        "validations": [{"id": "V1", "inputs": ["P1"], "method": {}, "provenance": []}],
        "claims": [{"id": "C1", "inputs": ["V1"], "method": {}, "provenance": []}],
    })
    graph_path = output / "preprocessing" / "paper_graph.json"
    write_json(graph_path, graph.model_dump(mode="json"))
    node_state = output / "graph" / "node_state.json"
    graph_sha = sha256_file(graph_path)
    write_empty_node_state(node_state, graph_sha)
    merge_node_updates(node_state, graph, graph_sha, "codegen:001", [
        {"node_id": "P1", "issues": [{"description": "Earlier recorded assumption"}]},
    ])
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    for name in ("prep.py", "train.py", "obsolete.py"):
        (codebase / name).write_text("original\n")
    remote = mode == "interrupted_remote"
    plan_path = codebase / "codegen_plan.json"
    write_json(plan_path, {
        "files": [{"path": "prep.py", "responsibility": "P1"}],
        "dependency_order": ["prep.py"], "entry_points": ["python prep.py"],
        "shared_state": "", "node_updates": [],
        "remote_compute": {
            "state_path": str(output / "remote_compute" / "instance.json"),
            "remote_working_dir": "/workspace/study", "remote_dataset_dir": "/data",
        } if remote else None,
    })
    plan_bytes = plan_path.read_bytes()
    report_path = output / "codegen" / "audit" / "attempt_001" / "audit_report.json"
    write_json(report_path, {"verdict": "FAIL", "issues": [
        {"node_id": "P1", "description": "Unspecified cohort decision", "route": "preprocessing_fix",
         "editable_paths": [] if mode == "record_only" else ["prep.py", "helper.py", "obsolete.py"]},
        {"node_id": "P1", "description": "Missing source component", "route": "source_unavailable"},
    ]})
    pipeline.start_stage("audit_agent")
    pipeline.update_stage_checkpoints("audit_agent", {
        "verdict": "FAIL", "report_path": str(report_path), "refine_rounds_used": 1,
    })
    pipeline.complete_stage("audit_agent", [str(report_path)])
    state = {
        "config": config, "paper_graph_path": str(graph_path),
        "paper_markdown": str(tmp_path / "paper.md"), "node_state_path": str(node_state),
        "codebase_dir": str(codebase),
    }
    calls = []
    remote_calls = []
    monkeypatch.setattr("medai.workflow.validate_codegen_remote_compute", lambda *args, **kw: None)
    monkeypatch.setattr("medai.workflow._run_computation_provider_action",
                        lambda *args, **kw: remote_calls.append((args, kw)))

    def fake_agent(**kwargs):
        candidate = kwargs["working_dir"]
        scratch = candidate / ".medai_refine"
        calls.append(kwargs)
        assert candidate.name == "candidate_codebase"
        assert kwargs["confine_to_working_dir"] is True
        assert (codebase / "prep.py").read_text() == "original\n"
        assert not (candidate.parent / "baseline_codebase").exists()
        if len(calls) == 1:
            prompt = kwargs["prompt_path"].read_text()
            assert "This coverage review never triggers failure exit" in " ".join(prompt.split())
            assert str(candidate) in prompt
        else:
            assert kwargs["resume_session_id"] == "refine-session"
        kwargs["transcript_path"].write_text("preserved transcript\n")
        if mode != "record_only":
            (candidate / "prep.py").write_text("corrected\n")
            (candidate / "helper.py").write_text("helper\n")
            (candidate / "obsolete.py").unlink(missing_ok=True)
        if mode == "repair":
            (candidate / "train.py").write_text("forbidden\n" if len(calls) == 1 else "original\n")
        dispositions = [{"description": "Omission handled", "audit_issue": 1,
                         "resolution": "Implemented a medically justified assumption", "custom": {"open": True}}]
        # More than two coverage continuations must not exhaust artifact repairs.
        if mode != "repair" or len(calls) >= 5:
            dispositions.append({"description": "Source absence confirmed", "audit_issue": 2,
                                 "resolution": "Record remaining limitation and request availability review"})
        write_json(scratch / "node_updates.json", [{"node_id": "P1", "issues": dispositions}])
        write_json(scratch / "results" / "counts.json", {"actual": 123})
        return "refine-session"

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    if remote:
        def interrupted_merge(*args, **kwargs):
            raise OSError("interrupted state write")

        monkeypatch.setattr("medai.workflow.merge_node_updates", interrupted_merge)
        with pytest.raises(OSError, match="interrupted state write"):
            cohort_refine_agent_node(state)
        assert (codebase / "prep.py").read_text() == "corrected\n"
        assert len(calls) == 1
        monkeypatch.setattr("medai.workflow.merge_node_updates", merge_node_updates)

    assert cohort_refine_agent_node(state) == {"codebase_dir": str(codebase)}
    assert len(calls) == (5 if mode == "repair" else 1)
    candidate = calls[0]["working_dir"]
    assert not candidate.exists()
    assert calls[0]["transcript_path"].read_text() == "preserved transcript\n"
    retained = candidate.parent / "refinement"
    assert json.loads((retained / "results" / "counts.json").read_text()) == {"actual": 123}
    assert plan_path.read_bytes() == plan_bytes
    assert (codebase / "train.py").read_text() == "original\n"
    assert (codebase / "prep.py").read_text() == ("original\n" if mode == "record_only" else "corrected\n")
    updates = load_node_state(node_state).updates
    assert {update.source for update in updates} == {"codegen:001", "cohort_refine:001"}
    assert len(next(update for update in updates if update.source == "cohort_refine:001").issues) == 2
    assert bool(remote_calls) is remote
    if remote:
        assert any(args[1] == "upload" for args, _ in remote_calls)
        assert any(kw["arguments"][-1].endswith("/candidate_codebase") for _, kw in remote_calls)
    cohort_refine_agent_node(state)  # Completed resume must use retained updates, not deleted code.
    assert len(calls) == (5 if mode == "repair" else 1)
    assert len(load_node_state(node_state).updates) == 2


def test_refinement_rejects_symlink_at_an_allowed_file(tmp_path: Path) -> None:
    from medai.cohort_refinement import refinement_manifest, validate_refinement_candidate

    codebase = tmp_path / "codebase"
    candidate = tmp_path / "candidate"
    codebase.mkdir()
    candidate.mkdir()
    (codebase / "prep.py").write_text("original\n")
    outside = tmp_path / "protected.py"
    outside.write_text("protected\n")
    (candidate / "prep.py").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        validate_refinement_candidate(codebase, candidate, refinement_manifest(codebase), {"prep.py"})
    assert outside.read_text() == "protected\n"
