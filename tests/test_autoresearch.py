import json
from pathlib import Path

import pytest

from medai.autoresearch import (
    REQUIRED_BASE_STAGES,
    autoresearch_preflight_node,
    create_autoresearch_workflow,
)
from medai.config import AutoResearchConfig
from medai.pipeline_state import (
    PipelineState,
    build_autoresearch_inputs,
)


def _prepare_base_run(tmp_path: Path) -> Path:
    base_run = tmp_path / "base"
    codebase = base_run / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    (base_run / "preprocessing" / "artifacts").mkdir(parents=True)
    (base_run / "plan").mkdir()
    (base_run / "replication" / "E1").mkdir(parents=True)
    (base_run / "report").mkdir()
    (base_run / "preprocessing" / "paper.md").write_text(
        "# Predictive paper\n",
        encoding="utf-8",
    )
    (base_run / "preprocessing" / "claims.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "claim_id": "C1",
                        "statement": "Accuracy is reported.",
                        "role": "validation",
                        "kind": "numeric",
                        "paper_result": 0.8,
                        "provenance": {
                            "page": 1,
                            "section": "Results",
                            "quote": "Accuracy was 0.8.",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (base_run / "preprocessing" / "experiment_todo.json").write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "experiment_id": "E1",
                        "description": "Train and evaluate.",
                        "claims": ["C1"],
                        "artifacts": ["Figure 1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (codebase / "baseline.py").write_text("print('baseline')\n", encoding="utf-8")
    (codebase / "metrics.json").write_text('{"accuracy": 0.8}\n', encoding="utf-8")
    (codebase / "figure.png").write_bytes(b"png")
    (codebase / "codegen_plan.json").write_text(
        json.dumps(
            {
                "files": [{"path": "baseline.py", "responsibility": "baseline"}],
                "dependency_order": ["baseline.py"],
                "entry_points": ["baseline.py"],
                "shared_state": "metrics",
                "ambiguities": [],
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "environment": {
            "language": "Python",
            "key_dependencies": [],
            "setup_hints": "Use CPU.",
        },
        "steps": [
            {
                "id": 1,
                "description": "Prepare.",
                "command_hint": "python --version",
                "expected_outcome": "Print version.",
                "verifies": [],
            },
            {
                "id": 2,
                "description": "Evaluate.",
                "command_hint": "python baseline.py",
                "expected_outcome": "Write metrics.json.",
                "verifies": ["C1"],
            },
            {
                "id": 3,
                "description": "Render.",
                "command_hint": "python plot.py",
                "expected_outcome": "Write figure.png.",
                "verifies": ["Figure 1"],
            },
        ],
    }
    (base_run / "plan" / "replicate_plan.json").write_text(
        json.dumps(plan),
        encoding="utf-8",
    )
    (base_run / "replication" / "replication_log.json").write_text(
        json.dumps(
            {
                "step_outcomes": [
                    {
                        "step_id": step["id"],
                        "description": step["description"],
                        "command_executed": step["command_hint"],
                        "exit_code": 0,
                        "stdout": "done",
                        "stderr": "",
                        "output_files": (
                            []
                            if step["id"] == 1
                            else ["metrics.json" if step["id"] == 2 else "figure.png"]
                        ),
                        "duration_seconds": 1.0,
                        "fixes_applied": [],
                        "code_modified": False,
                        "notes": "",
                    }
                    for step in plan["steps"]
                ]
            }
        ),
        encoding="utf-8",
    )
    (base_run / "replication" / "evidence_summary.json").write_text(
        json.dumps(
            {
                "environment": {
                    "python_version": "3.10",
                    "gpu_available": False,
                    "gpu_model": None,
                    "key_packages": {},
                }
            }
        ),
        encoding="utf-8",
    )
    (base_run / "report" / "reproduction_report.md").write_text(
        "# Reproduction Report\n\n"
        "## 1. Per-experiment reports\nE1 C1 Figure 1\n\n"
        "## 2. Validation claim assessment\nC1 close\n\n"
        "## 3. Replication risk list\nNo ambiguities were recorded.\n",
        encoding="utf-8",
    )
    state = PipelineState.create(
        base_run,
        {"provider": "codex", "data": None, "smart_replicate": False},
    )
    for stage in REQUIRED_BASE_STAGES:
        state.start_stage(stage)
        state.complete_stage(stage, [])
    state.mark_completed()
    return base_run


def _configure_fake_agents(
    monkeypatch,
    config: AutoResearchConfig,
    *,
    valid_first_idea: bool,
    audit_fails_twice: bool,
    eligible: bool = True,
):
    contexts = {}
    calls = []

    def fake_render(template_name, destination, **context):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(template_name, encoding="utf-8")
        contexts[destination] = (template_name, context)
        return destination

    def fake_agent(*, prompt_path, transcript_path, working_dir, **kwargs):
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
        template_name, context = contexts[prompt_path]
        calls.append((template_name, prompt_path, context))
        idea_id = context.get("idea_id")

        if template_name.endswith("eligibility/session_instructions.md"):
            payload = {
                "eligible": eligible,
                "reason": "Supervised prediction task" if eligible else "Statistical analysis",
                "evidence_paths": [str(config.base_run / "preprocessing" / "paper.md")],
                "anchors": (
                    {
                        "task": "classification",
                        "prediction_target": "outcome",
                        "dataset": "local cohort",
                        "cohort": "fixed cohort",
                        "inputs": ["features"],
                        "outputs": ["risk score"],
                        "metrics": ["accuracy"],
                        "experiment_protocol": ["fixed split"],
                        "baseline_method": "base classifier",
                    }
                    if eligible
                    else None
                ),
            }
            Path(context["eligibility_path"]).write_text(
                json.dumps(payload), encoding="utf-8"
            )
        elif template_name.endswith("idea_generation/session_instructions.md"):
            text = f"# Round {context['round_index']}\n\n"
            for current_id in context["idea_ids"]:
                text += (
                    f"## {current_id}\n\n"
                    "### Description\nA nontrivial refinement.\n\n"
                    "### Motivation\nAn observed modeling limitation.\n\n"
                    "### Provenance\nSupporting paper.\n\n"
                )
            Path(context["ideas_path"]).write_text(text, encoding="utf-8")
        elif template_name.endswith("codegen/session_instructions.md"):
            Path(working_dir, "refinement.txt").write_text(str(idea_id), encoding="utf-8")
            if context["repair_audit_path"]:
                Path(working_dir, "audit_repair.txt").write_text("repaired", encoding="utf-8")
            Path(context["implementation_plan_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "summary": "Add refinement.",
                        "change_points": [
                            {
                                "path": "refinement.txt",
                                "change": "Add refinement marker.",
                                "rationale": "Keep baseline available.",
                            }
                        ],
                        "baseline_entry_points": ["python baseline.py"],
                        "refinement_entry_points": ["python refined.py"],
                        "preserved_anchors": [
                            "task_and_prediction_target",
                            "dataset_cohort_and_io",
                            "metrics_and_protocol",
                            "baseline_method",
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("audit/session_instructions.md"):
            attempt = int(Path(context["audit_path"]).stem.rsplit("_", 1)[1])
            fail = idea_id.endswith("I01") and (attempt == 1 or audit_fails_twice)
            anchors = [
                "task_and_prediction_target",
                "dataset_cohort_and_io",
                "metrics_and_protocol",
                "baseline_method",
            ]
            Path(context["audit_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "verdict": "fail" if fail else "pass",
                        "checks": [
                            {
                                "anchor": anchor,
                                "verdict": "fail" if fail and index == 0 else "pass",
                                "evidence": ["base/refinement diff"],
                                "issue": "target changed" if fail and index == 0 else None,
                            }
                            for index, anchor in enumerate(anchors)
                        ],
                        "required_fixes": ["restore target"] if fail else [],
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("plan/session_instructions.md"):
            Path(context["experiment_plan_path"]).write_text(
                json.dumps(
                    {
                        "environment": {
                            "language": "Python",
                            "key_dependencies": [],
                            "setup_hints": "Use CPU.",
                        },
                        "steps": [
                            {
                                "id": 1,
                                "description": "Prepare.",
                                "command_hint": "python --version",
                                "expected_outcome": "Print version.",
                                "verifies": [],
                            },
                            {
                                "id": 2,
                                "description": "Run refinement.",
                                "command_hint": "python refined.py",
                                "expected_outcome": "Write metrics.",
                                "verifies": ["refinement"],
                            },
                            {
                                "id": 3,
                                "description": "Verify metric.",
                                "command_hint": "python verify.py",
                                "expected_outcome": "Write evidence.",
                                "verifies": ["accuracy"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("experiment/session_instructions.md"):
            experiment_dir = Path(context["experiment_dir"])
            result_path = experiment_dir / "metrics.json"
            result_path.write_text('{"accuracy": 0.81}\n', encoding="utf-8")
            Path(context["experiment_log_path"]).write_text(
                json.dumps(
                    {
                        "step_outcomes": [
                            {
                                "step_id": step_id,
                                "description": "step",
                                "command_executed": "python command.py",
                                "exit_code": 0,
                                "stdout": "done",
                                "stderr": "",
                                "output_files": [] if step_id == 1 else [str(result_path)],
                                "duration_seconds": 1.0,
                                "fixes_applied": [],
                                "code_modified": False,
                                "notes": "",
                            }
                            for step_id in (1, 2, 3)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            Path(context["evidence_summary_path"]).write_text(
                json.dumps(
                    {
                        "environment": {
                            "python_version": "3.10",
                            "gpu_available": False,
                            "gpu_model": None,
                            "key_packages": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("assessment/session_instructions.md"):
            is_valid = valid_first_idea and idea_id.endswith("I01")
            refined = 0.81 if is_valid else 0.79
            delta = refined - 0.8
            Path(context["assessment_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "verdict": "valid" if is_valid else "invalid",
                        "summary": "metric comparison complete",
                        "audit_passed": True,
                        "protocol_consistent": True,
                        "primary_metric": {
                            "name": "accuracy",
                            "direction": "higher",
                            "baseline_value": 0.8,
                            "refined_value": refined,
                            "absolute_delta": delta,
                            "relative_delta": delta / 0.8,
                            "uncertainty_available": False,
                            "noise_threshold": None,
                            "uncertainty_method": None,
                            "improvement_supported": is_valid,
                        },
                        "secondary_metrics": [],
                        "evidence_paths": [str(context["experiment_log_path"])],
                        "failure_reasons": [] if is_valid else ["No improvement"],
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("report/session_instructions.md"):
            rounds = json.loads(context["rounds_json"])
            idea_ids = []
            for round_paths in rounds:
                summary = json.loads(Path(round_paths["summary"]).read_text(encoding="utf-8"))
                idea_ids.extend(idea["idea_id"] for idea in summary["ideas"])
            Path(context["report_path"]).write_text(
                "# Auto Research Report\n\n"
                "## 1. Base problem and anchors\nclassification\n\n"
                "## 2. Idea ledger\n"
                + " ".join(idea_ids)
                + "\n\n## 3. Experiment comparisons\nevidence\n\n"
                "## 4. Validity and failure assessment\nall verdicts\n\n"
                "## 5. Visualizations\n"
                "![metrics](idea_metric_comparison.png)\n"
                "![status](idea_status_overview.png)\n",
                encoding="utf-8",
            )

    monkeypatch.setattr("medai.autoresearch.render_prompt", fake_render)
    monkeypatch.setattr("medai.autoresearch.run_agent", fake_agent)
    monkeypatch.setattr(
        "medai.autoresearch.detect_resources",
        lambda path: {"cpu": {}, "memory": {}, "disk": {}, "gpus": []},
    )
    return contexts, calls


def _prepare_campaign(tmp_path: Path, monkeypatch, max_iter: int) -> AutoResearchConfig:
    base_run = _prepare_base_run(tmp_path)
    skills = tmp_path / "skills"
    (skills / "idea-generation").mkdir(parents=True)
    (skills / "idea-generation" / "SKILL.md").write_text(
        "---\ndescription: Generate research ideas.\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("medai.autoresearch.skills_dir", lambda: skills)
    config = AutoResearchConfig.create(
        base_run=base_run,
        output=tmp_path / "autoresearch",
        provider=None,
        max_iter=max_iter,
        siliconflow_config=None,
    )
    PipelineState.create(config.output, build_autoresearch_inputs(config))
    return config


def test_autoresearch_completes_all_three_ideas_and_resumes(tmp_path: Path, monkeypatch):
    config = _prepare_campaign(tmp_path, monkeypatch, max_iter=1)
    _, calls = _configure_fake_agents(
        monkeypatch,
        config,
        valid_first_idea=True,
        audit_fails_twice=False,
    )

    result = create_autoresearch_workflow().invoke({"config": config})

    assert PipelineState(config.output).state["status"] == "completed"
    assert Path(result["report_path"]).is_file()
    for idea_index in range(1, 4):
        idea_dir = config.output / "rounds" / "round_001" / "ideas" / f"idea_{idea_index:02d}"
        assert (idea_dir / "assessment" / "assessment.json").is_file()
        assert (idea_dir / "codegen" / "codebase" / "refinement.txt").read_text() == (
            f"R01-I{idea_index:02d}"
        )
    assert not (config.base_run / "codegen" / "codebase" / "refinement.txt").exists()
    assert (config.output / "report" / "idea_metric_comparison.png").read_bytes().startswith(
        b"\x89PNG"
    )
    assert (config.output / "report" / "idea_status_overview.png").read_bytes().startswith(
        b"\x89PNG"
    )
    assert any("codegen_repair" in str(call[1]) for call in calls)

    call_count = len(calls)
    PipelineState(config.output).resume(build_autoresearch_inputs(config))
    create_autoresearch_workflow().invoke({"config": config})
    assert len(calls) == call_count


def test_autoresearch_retries_rounds_and_skips_audit_failed_experiments(
    tmp_path: Path,
    monkeypatch,
):
    config = _prepare_campaign(tmp_path, monkeypatch, max_iter=2)
    contexts, _ = _configure_fake_agents(
        monkeypatch,
        config,
        valid_first_idea=False,
        audit_fails_twice=True,
    )

    create_autoresearch_workflow().invoke({"config": config})

    for round_index in (1, 2):
        idea_dir = (
            config.output
            / "rounds"
            / f"round_{round_index:03d}"
            / "ideas"
            / "idea_01"
        )
        assert not (idea_dir / "plan" / "experiment_plan.json").exists()
        assessment = json.loads(
            (idea_dir / "assessment" / "assessment.json").read_text(encoding="utf-8")
        )
        assert assessment["verdict"] == "invalid"
        assert assessment["audit_passed"] is False

    round_two_prompt = config.output / "prompts" / "round_002" / "idea_generation.md"
    _, round_two_context = contexts[round_two_prompt]
    assert "round_001/ideas.md" in round_two_context["prior_rounds_json"]
    assert "round_001/round_summary.json" in round_two_context["prior_rounds_json"]
    assert PipelineState(config.output).state["status"] == "completed"


def test_autoresearch_ineligible_and_missing_skill_stop_before_ideas(
    tmp_path: Path,
    monkeypatch,
):
    config = _prepare_campaign(tmp_path, monkeypatch, max_iter=1)
    _configure_fake_agents(
        monkeypatch,
        config,
        valid_first_idea=False,
        audit_fails_twice=False,
        eligible=False,
    )
    create_autoresearch_workflow().invoke({"config": config})
    assert PipelineState(config.output).state["status"] == "ineligible"
    assert not (config.output / "rounds" / "round_001").exists()

    second_root = tmp_path / "missing-skill"
    second_root.mkdir()
    second_base = _prepare_base_run(second_root)
    second_config = AutoResearchConfig.create(
        base_run=second_base,
        output=second_root / "autoresearch",
        provider=None,
        max_iter=1,
        siliconflow_config=None,
    )
    PipelineState.create(second_config.output, build_autoresearch_inputs(second_config))
    monkeypatch.setattr("medai.autoresearch.skills_dir", lambda: second_root / "skills")
    with pytest.raises(RuntimeError, match="idea-generation skill is missing"):
        autoresearch_preflight_node({"config": second_config})
