from __future__ import annotations

import json
from pathlib import Path

import pytest

from medai.artifacts import write_json
from medai.config import RunConfig
from medai.data_availability import sha256_file
from medai.models import (
    GraphExecutionScope,
    PaperGraph,
    ReplicationPlan,
    validate_replication_plan,
    validate_reproduction_report,
)
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.study_graph import write_empty_node_state
from medai.workflow import (
    _compose_reproduction_report,
    report_agents_node,
    validate_replication_artifacts,
)


def _node(node_id: str, inputs: list[str], result=None) -> dict[str, object]:
    return {
        "id": node_id,
        "inputs": inputs,
        "method": {"operation": node_id},
        "paper_result": result,
        "provenance": [{"page": 1}],
    }


def _graph() -> PaperGraph:
    return PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [_node("P1", ["D1"])],
            "training": [],
            "models": [],
            "validations": [_node("V1", ["P1"])],
            "claims": [_node("C1", ["V1"], result=0.8)],
        }
    )


def _plan(verifies: list[list[str]]) -> ReplicationPlan:
    return ReplicationPlan.model_validate(
        {
            "environment": {"language": "Python", "key_dependencies": [], "setup_hints": ""},
            "steps": [
                {
                    "id": index,
                    "description": f"step {index}",
                    "command_hint": "python run.py",
                    "expected_outcome": "artifact",
                    "verifies": node_ids,
                }
                for index, node_ids in enumerate(verifies, 1)
            ],
            "remote_compute": None,
        }
    )


def _scope(graph_path: Path, graph: PaperGraph) -> GraphExecutionScope:
    payload = {
        "paper_graph_sha256": sha256_file(graph_path),
        "availability_report_sha256": "2" * 64,
        "verdict": "FULL",
        "runnable_node_ids": [node.id for node in graph.nodes],
        "blocked_nodes": [],
        "active_sources": [],
        "execution_location": "local",
    }
    import hashlib

    payload["scope_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GraphExecutionScope.model_validate(payload)


def test_replication_plan_covers_all_runnable_nodes() -> None:
    graph = _graph()
    scope = GraphExecutionScope(
        paper_graph_sha256="1" * 64,
        availability_report_sha256="2" * 64,
        scope_sha256="3" * 64,
        verdict="FULL",
        runnable_node_ids=[node.id for node in graph.nodes],
        blocked_nodes=[],
        active_sources=[],
        execution_location="local",
    )
    validate_replication_plan(graph, scope, _plan([["D1"], ["P1"], ["V1", "C1"]]))

    with pytest.raises(ValueError, match="does not cover"):
        validate_replication_plan(graph, scope, _plan([["D1"], ["P1"], ["V1"]]))


def test_plan_prompt_requires_predecessor_artifacts_and_reverse_audit(
    tmp_path: Path,
) -> None:
    graph = _graph()
    prompt = render_prompt(
        "plan/session_instructions.md",
        tmp_path / "plan.md",
        codebase_dir=tmp_path / "codebase",
        paper_markdown=tmp_path / "paper.md",
        paper_graph_path=tmp_path / "paper_graph.json",
        execution_scope_path=tmp_path / "execution_scope.json",
        data_paths=(tmp_path / "data",),
        gpu_info=[],
        paper_graph=graph.model_dump(mode="json"),
        runnable_node_ids=[node.id for node in graph.nodes],
        cloud_drive_enabled=False,
        replicate_plan_path=tmp_path / "replicate_plan.json",
    ).read_text(encoding="utf-8")

    assert "Name every direct input from the graph" in prompt
    assert "A node ID appearing only in `verifies`" in prompt
    assert "Mandatory reverse plan self-audit" in prompt
    assert "start separately from every runnable terminal C" in prompt
    assert "producer and consumer share a step" in prompt


@pytest.mark.parametrize("bad_field", ["result", "evidence"])
def test_replication_requires_result_and_real_evidence(tmp_path: Path, bad_field: str) -> None:
    output = tmp_path / "run"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"paper")
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    graph = _graph()
    graph_path = output / "preprocessing" / "paper_graph.json"
    write_json(graph_path, graph.model_dump(mode="json"))
    graph_sha = sha256_file(graph_path)
    node_state_path = output / "graph" / "node_state.json"
    write_empty_node_state(node_state_path, graph_sha)
    scope = _scope(graph_path, graph)
    scope_path = output / "preprocessing" / "execution_scope.json"
    write_json(scope_path, scope.model_dump(mode="json"))
    codebase = output / "codegen" / "codebase"
    replication = output / "replication"
    codebase.mkdir(parents=True)
    replication.mkdir(parents=True)
    evidence_path = codebase / "result.json"
    evidence_path.write_text("{}\n", encoding="utf-8")
    plan = _plan([["D1"], ["P1"], ["V1", "C1"]])
    plan_path = output / "plan" / "replicate_plan.json"
    write_json(plan_path, plan.model_dump(mode="json"))
    updates = [
        {
            "node_id": node.id,
            "result": {"actual": node.id},
            "evidence": [str(evidence_path)],
            "issues": [],
        }
        for node in graph.nodes
    ]
    updates[-1][bad_field] = None if bad_field == "result" else []
    write_json(
        replication / "replication_log.json",
        {
            "step_outcomes": [
                {
                    "step_id": step.id,
                    "description": step.description,
                    "command_executed": "python run.py",
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                    "output_files": [str(evidence_path)],
                    "duration_seconds": 1,
                    "fixes_applied": [],
                    "code_modified": False,
                    "notes": "",
                }
                for step in plan.steps
            ],
            "node_updates": updates,
        },
    )
    write_json(
        replication / "evidence_summary.json",
        {
            "environment": {
                "python_version": "3.12",
                "gpu_available": False,
                "gpu_model": None,
                "key_packages": {},
            }
        },
    )
    state = {
        "config": config,
        "paper_graph_path": str(graph_path),
        "node_state_path": str(node_state_path),
        "execution_scope_path": str(scope_path),
        "replicate_plan_path": str(plan_path),
        "codebase_dir": str(codebase),
    }

    with pytest.raises(RuntimeError, match="no actual"):
        validate_replication_artifacts(state)  # type: ignore[arg-type]


def test_claim_fragments_are_composed_in_graph_order(tmp_path: Path) -> None:
    graph = _graph()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    fragment = """# Claim C1

Paper result: 0.8

Reproduced result: 0.79

Upstream node results: D1 -> P1 -> V1

Direct comparison: relative error 1.25%

Scope blockers: none

Lineage issues: none

Assessment: close
"""
    (claims_dir / "C1.md").write_text(fragment, encoding="utf-8")
    report_path = tmp_path / "reproduction_report.md"

    _compose_reproduction_report(graph, claims_dir, report_path)

    report = report_path.read_text(encoding="utf-8")
    assert report.startswith("# Reproduction Report\n\n## Claim C1")


def test_reproduction_report_distinguishes_prefix_claim_ids() -> None:
    graph = PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [_node("P1", ["D1"])],
            "training": [],
            "models": [],
            "validations": [_node("V1", ["P1"])],
            "claims": [
                _node("C1", ["V1"], result=0.8),
                _node("C10", ["V1"], result=0.7),
            ],
        }
    )
    report = """# Reproduction Report

## Claim C1

Paper result: 0.8
Reproduced result: 0.79
Upstream node results: D1 -> P1 -> V1
Direct comparison: relative error 1.25%
Scope blockers: none
Lineage issues: none
Assessment: close

## Claim C10

Paper result: 0.7
Reproduced result: 0.69
Upstream node results: D1 -> P1 -> V1
Direct comparison: relative error 1.43%
Scope blockers: none
Lineage issues: none
Assessment: close
"""

    validate_reproduction_report(report, graph)


def test_legacy_manifest_is_rejected_without_writeback(tmp_path: Path) -> None:
    output = tmp_path / "legacy"
    output.mkdir()
    manifest = output / "manifest.json"
    manifest.write_text(
        json.dumps({"version": 5, "inputs": {}, "stages": {}, "status": "completed"}),
        encoding="utf-8",
    )
    before = manifest.read_bytes()

    with pytest.raises(RuntimeError, match="read-only"):
        PipelineState(output)

    assert manifest.read_bytes() == before


def test_report_resume_skips_valid_completed_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "run"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"paper")
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    payload = _graph().model_dump(mode="python")
    payload["claims"].append(_node("C2", ["V1"], result=0.75))
    graph = PaperGraph.model_validate(payload)
    graph_path = output / "preprocessing" / "paper_graph.json"
    write_json(graph_path, graph.model_dump(mode="json"))
    node_state_path = output / "graph" / "node_state.json"
    write_empty_node_state(node_state_path, sha256_file(graph_path))
    scope = _scope(graph_path, graph)
    scope_path = output / "preprocessing" / "execution_scope.json"
    write_json(scope_path, scope.model_dump(mode="json"))

    claims_dir = output / "report" / "claims"
    claims_dir.mkdir(parents=True)

    def fragment(claim_id: str, paper_result: str) -> str:
        return f"""# Claim {claim_id}

Paper result: {paper_result}
Reproduced result: available
Upstream node results: available
Direct comparison: assessed
Scope blockers: none
Lineage issues: none
Assessment: close
"""

    (claims_dir / "C1.md").write_text(fragment("C1", "0.8"), encoding="utf-8")
    (claims_dir / "C1_transcript.jsonl").write_text("{}\n", encoding="utf-8")
    pipeline = PipelineState.create(output, {"provider": "codex"})
    pipeline.start_stage("report_agents")
    pipeline.update_stage_checkpoints(
        "report_agents",
        {"scope_sha256": scope.scope_sha256, "completed_claims": ["C1"]},
    )
    pipeline.fail("interrupted")

    invoked: list[str] = []

    def fake_run_agent(**kwargs):
        prompt = Path(kwargs["prompt_path"]).read_text(encoding="utf-8")
        assert "C2" in prompt
        invoked.append("C2")
        (claims_dir / "C2.md").write_text(fragment("C2", "0.75"), encoding="utf-8")
        Path(kwargs["transcript_path"]).write_text("{}\n", encoding="utf-8")
        return "session"

    def fake_validate(**kwargs):
        kwargs["validate"]()

    monkeypatch.setattr("medai.workflow.run_agent", fake_run_agent)
    monkeypatch.setattr(
        "medai.workflow._validate_agent_artifacts_with_resume", fake_validate
    )
    state = {
        "config": config,
        "paper_markdown": str(output / "preprocessing" / "paper.md"),
        "paper_graph_path": str(graph_path),
        "node_state_path": str(node_state_path),
        "execution_scope_path": str(scope_path),
        "replicate_plan_path": str(output / "plan" / "replicate_plan.json"),
        "codebase_dir": str(output / "codegen" / "codebase"),
    }

    report_agents_node(state)  # type: ignore[arg-type]

    assert invoked == ["C2"]
    checkpoint = PipelineState(output).get_stage_checkpoints("report_agents")
    assert checkpoint["completed_claims"] == ["C1", "C2"]
    report = (output / "report" / "reproduction_report.md").read_text(encoding="utf-8")
    assert report.index("## Claim C1") < report.index("## Claim C2")
