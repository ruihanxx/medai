import json
from pathlib import Path

import pytest

from medai.config import RunConfig
from medai.pipeline_state import PipelineState
from medai.workflow import (
    audit_agent_node,
    audit_route,
    codegen_agent_node,
    read_audit_verdict,
)


def _write_codegen_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "files": [{"path": "run.py", "responsibility": "Run experiment"}],
                "dependency_order": ["run.py"],
                "entry_points": ["run.py"],
                "shared_state": "Files",
                "remote_compute": None,
                "ambiguities": [
                    {
                        "question": "Missing-value handling is unspecified.",
                        "assumption": "Preserve target rows and impute features only.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _audit_state(tmp_path: Path) -> dict[str, object]:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "data"
    data.mkdir()
    output = tmp_path / "output"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=data,
        siliconflow_config=None,
    )
    PipelineState.create(output, {"paper": str(paper), "data": str(data)})

    resources_path = output / "preflight" / "resources.json"
    resources_path.parent.mkdir(parents=True)
    resources_path.write_text('{"gpus": []}\n', encoding="utf-8")
    paper_markdown = output / "preprocessing" / "paper.md"
    paper_markdown.parent.mkdir()
    paper_markdown.write_text("# Paper\n", encoding="utf-8")
    claims_path = output / "preprocessing" / "claims.json"
    claims_path.write_text("{}\n", encoding="utf-8")
    experiments_path = output / "preprocessing" / "experiment_todo.json"
    experiments_path.write_text("{}\n", encoding="utf-8")
    dataset_patch_path = output / "system_maintenance" / "dataset" / "patch.json"
    dataset_patch_path.parent.mkdir(parents=True)
    dataset_patch_path.write_text("[]\n", encoding="utf-8")
    skill_corrections_path = output / "system_maintenance" / "skills" / "corrections.json"
    skill_corrections_path.parent.mkdir(parents=True)
    skill_corrections_path.write_text("[]\n", encoding="utf-8")
    codebase_dir = output / "codegen" / "codebase"
    codebase_dir.mkdir(parents=True)
    codegen_plan_path = codebase_dir / "codegen_plan.json"
    _write_codegen_plan(codegen_plan_path)
    transcript_path = output / "codegen" / "codegen_transcript.jsonl"
    transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
    (output / "prompts").mkdir()

    pipeline_state = PipelineState(output)
    pipeline_state.start_stage("codegen_agent")
    pipeline_state.update_stage_checkpoints(
        "codegen_agent", {"source_prepared": True}
    )
    pipeline_state.complete_stage(
        "codegen_agent",
        [str(codebase_dir), str(codegen_plan_path), str(transcript_path)],
    )
    return {
        "config": config,
        "paper_markdown": str(paper_markdown),
        "resources_path": str(resources_path),
        "claims_path": str(claims_path),
        "experiments_path": str(experiments_path),
        "codebase_dir": str(codebase_dir),
    }


def _fake_agents(verdicts: list[str], codegen_prompts: list[str]):
    remaining = list(verdicts)

    def fake_agent(*, prompt_path, working_dir, transcript_path, **kwargs):
        transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
        if prompt_path.name.startswith("audit_attempt_"):
            verdict = remaining.pop(0)
            (working_dir / "audit_report.md").write_text(
                "# Preprocessing Audit Report\n\n"
                "## Scope\n\nLocal preprocessing.\n\n"
                "## Paper expectations\n\nA stable cohort.\n\n"
                "## Commands executed\n\n`python preprocess.py`\n\n"
                "## Observed statistics\n\nCounts recorded.\n\n"
                "## Sanity assessment\n\nReviewed.\n\n"
                "## Limitations\n\nNone.\n\n"
                "## Required codegen changes\n\nSee assessment.\n\n"
                f"Verdict: {verdict}\n",
                encoding="utf-8",
            )
        else:
            codegen_prompts.append(prompt_path.read_text(encoding="utf-8"))
            _write_codegen_plan(Path(working_dir) / "codegen_plan.json")

    return fake_agent


def test_failed_audit_revises_preprocessing_then_passes(
    tmp_path: Path,
    monkeypatch,
):
    state = _audit_state(tmp_path)
    config = state["config"]
    assert isinstance(config, RunConfig)
    codegen_prompts: list[str] = []
    monkeypatch.setattr(
        "medai.workflow.run_agent",
        _fake_agents(["FAIL", "PASS"], codegen_prompts),
    )

    first = audit_agent_node(state)
    assert first["audit_verdict"] == "FAIL"
    first_report = Path(first["audit_report_path"])

    pipeline_state = PipelineState(config.output)
    pipeline_state.resume({"paper": str(config.paper), "data": str(config.data)})
    for stage_name in ("plan_agent", "replicate_agent", "report_agents"):
        pipeline_state.start_stage(stage_name)
        pipeline_state.complete_stage(stage_name, [f"old-{stage_name}"])

    state.update(codegen_agent_node(state))
    after_revision = PipelineState(config.output)
    for stage_name in ("plan_agent", "replicate_agent", "report_agents"):
        assert after_revision.get_stage_status(stage_name) == "invalidated"
    assert len(codegen_prompts) == 1
    assert str(first_report) in codegen_prompts[0]
    assert "only the complete preprocessing chain" in codegen_prompts[0]
    assert "Do not change model definitions, training,\nevaluation" in codegen_prompts[0]

    PipelineState(config.output).resume(
        {"paper": str(config.paper), "data": str(config.data)}
    )
    second = audit_agent_node(state)
    assert second["audit_verdict"] == "PASS"
    assert audit_route(second) == "plan_agent"
    checkpoints = PipelineState(config.output).get_stage_checkpoints("audit_agent")
    assert checkpoints == {
        "audited_codegen_attempt": 2,
        "verdict": "PASS",
        "report_path": second["audit_report_path"],
        "rewrite_rounds_used": 1,
    }
    assert first_report.is_file()
    assert Path(second["audit_report_path"]).is_file()


@pytest.mark.parametrize("final_verdict", ["PASS", "FAIL"])
def test_audit_allows_three_rewrites_and_fourth_decision(
    tmp_path: Path,
    monkeypatch,
    final_verdict: str,
):
    state = _audit_state(tmp_path)
    config = state["config"]
    assert isinstance(config, RunConfig)
    monkeypatch.setattr(
        "medai.workflow.run_agent",
        _fake_agents(["FAIL", "FAIL", "FAIL", final_verdict], []),
    )

    for index in range(4):
        if index == 3 and final_verdict == "FAIL":
            with pytest.raises(RuntimeError, match="three codegen rewrite rounds"):
                audit_agent_node(state)
            break
        result = audit_agent_node(state)
        if result["audit_verdict"] == "FAIL":
            state.update(codegen_agent_node(state))

    pipeline_state = PipelineState(config.output)
    checkpoints = pipeline_state.get_stage_checkpoints("audit_agent")
    assert checkpoints["rewrite_rounds_used"] == 3
    assert checkpoints["audited_codegen_attempt"] == 4
    assert checkpoints["verdict"] == final_verdict
    assert pipeline_state.state["stages"]["codegen_agent"]["attempts"] == 4
    assert pipeline_state.state["stages"]["audit_agent"]["attempts"] == 4
    for attempt in range(1, 5):
        report_path = (
            config.output
            / "codegen"
            / "audit"
            / f"attempt_{attempt:03d}"
            / "audit_report.md"
        )
        assert report_path.is_file()
    if final_verdict == "PASS":
        assert pipeline_state.get_stage_status("audit_agent") == "completed"
        assert audit_route({"audit_verdict": "PASS"}) == "plan_agent"
    else:
        assert pipeline_state.get_stage_status("audit_agent") == "failed"
        assert pipeline_state.state["status"] == "failed"
        assert "plan_agent" not in pipeline_state.state["stages"]


def test_audit_provider_retry_reuses_scientific_attempt(
    tmp_path: Path,
    monkeypatch,
):
    state = _audit_state(tmp_path)
    config = state["config"]
    assert isinstance(config, RunConfig)
    calls = 0

    def interrupted_then_passes(*, prompt_path, working_dir, transcript_path, **kwargs):
        nonlocal calls
        calls += 1
        transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
        if calls == 1:
            raise RuntimeError("provider interrupted")
        assert "resuming after a technical interruption" in prompt_path.read_text(
            encoding="utf-8"
        )
        (working_dir / "audit_report.md").write_text(
            "# Audit\n\nVerdict: PASS\n", encoding="utf-8"
        )

    monkeypatch.setattr("medai.workflow.run_agent", interrupted_then_passes)
    with pytest.raises(RuntimeError, match="provider interrupted"):
        audit_agent_node(state)
    PipelineState(config.output).fail("provider interrupted")

    result = audit_agent_node(state)
    assert result["audit_verdict"] == "PASS"
    pipeline_state = PipelineState(config.output)
    assert pipeline_state.state["stages"]["audit_agent"]["attempts"] == 2
    assert pipeline_state.get_stage_checkpoints("audit_agent")["rewrite_rounds_used"] == 0
    audit_root = config.output / "codegen" / "audit"
    assert [path.name for path in audit_root.iterdir()] == ["attempt_001"]


def test_completed_pass_is_reused_without_running_provider(
    tmp_path: Path,
    monkeypatch,
):
    state = _audit_state(tmp_path)
    config = state["config"]
    assert isinstance(config, RunConfig)
    monkeypatch.setattr("medai.workflow.run_agent", _fake_agents(["PASS"], []))
    first = audit_agent_node(state)

    def must_not_run(**kwargs):
        raise AssertionError("completed audit should be reused")

    monkeypatch.setattr("medai.workflow.run_agent", must_not_run)
    second = audit_agent_node(state)
    assert second == first
    assert PipelineState(config.output).state["stages"]["audit_agent"]["attempts"] == 1


@pytest.mark.parametrize(
    "contents",
    [
        "# Audit\n",
        "# Audit\n\nVerdict: MAYBE\n",
        "Verdict: PASS\n\nMore text\n",
        "Verdict: FAIL\n\nVerdict: PASS\n",
    ],
)
def test_audit_report_rejects_missing_duplicate_or_illegal_verdict(
    tmp_path: Path,
    contents: str,
):
    report_path = tmp_path / "audit_report.md"
    report_path.write_text(contents, encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly one verdict"):
        read_audit_verdict(report_path)


def test_remote_state_is_local_only_audit_context(
    tmp_path: Path,
    monkeypatch,
):
    state = _audit_state(tmp_path)
    config = state["config"]
    assert isinstance(config, RunConfig)
    remote_state_path = config.output / "remote_compute" / "instance.json"
    remote_state_path.parent.mkdir()
    original_state = '{"provider":"autodl","released":false}\n'
    remote_state_path.write_text(original_state, encoding="utf-8")
    monkeypatch.setattr("medai.workflow.run_agent", _fake_agents(["PASS"], []))

    audit_agent_node(state)

    prompt = (config.output / "prompts" / "audit_attempt_001.md").read_text(
        encoding="utf-8"
    )
    assert str(remote_state_path) in prompt
    assert "must not connect to it or operate it" in prompt
    assert "complete metadata, modality pairing, label" in prompt
    assert remote_state_path.read_text(encoding="utf-8") == original_state
