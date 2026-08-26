import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from medai.autoresearch import (
    REQUIRED_BASE_STAGES,
    _AutoResearchEnvironmentSetupError,
    _copy_base_cloud_inventory,
    _mother_environment_validated,
    _prepare_autoresearch_command_instance,
    _run_autoresearch_provider_operation,
    _run_experiment_command_handoff,
    _run_plan_cloud_pull_handoff,
    _validate_base_run,
    create_autoresearch_workflow,
)
from medai.config import AutoResearchConfig
from medai.models import (
    AutoResearchCommand,
    IdeaGenerationArtifact,
    validate_idea_generation_artifact,
)
from medai.pipeline_state import (
    PipelineState,
    build_autoresearch_inputs,
)
from medai.prompts import render_prompt


def _prepare_base_run(tmp_path: Path) -> Path:
    base_run = tmp_path / "base"
    codebase = base_run / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    (base_run / "preflight").mkdir()
    (base_run / "preprocessing" / "artifacts").mkdir(parents=True)
    (base_run / "plan").mkdir()
    (base_run / "replication" / "E1").mkdir(parents=True)
    (base_run / "report").mkdir()
    (base_run / "preprocessing" / "paper.md").write_text(
        "# Predictive paper\n",
        encoding="utf-8",
    )
    (base_run / "preflight" / "resources.json").write_text(
        '{"cpu": {}, "memory": {}, "disk": {}, "gpus": []}\n',
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
                        "computational_demand": "The experiment needs the paper's stated GPU and memory capacity.",
                        "datasets": [
                            {
                                "name": "Cohort dataset",
                                "role": "training and evaluation",
                                "usage": "Construct the fixed cohort, train the model, and evaluate its fixed split.",
                            }
                        ],
                        "claims": ["C1"],
                        "artifacts": ["Figure 1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (base_run / "preprocessing" / "execution_scope.json").write_text(
        json.dumps(
            {
                "availability_report_sha256": "a" * 64,
                "scope_sha256": "b" * 64,
                "verdict": "FULL",
                "runnable_experiment_ids": ["E1"],
                "blocked_experiments": [],
                "active_sources": [],
                "execution_location": "local",
            }
        ),
        encoding="utf-8",
    )
    (codebase / "baseline.py").write_text("print('baseline')\n", encoding="utf-8")
    (codebase / ".cache").mkdir()
    (codebase / ".cache" / "stale.bin").write_bytes(b"cache")
    (codebase / "metrics.json").write_text('{"accuracy": 0.8}\n', encoding="utf-8")
    (codebase / "figure.png").write_bytes(b"png")
    (codebase / "codegen_plan.json").write_text(
        json.dumps(
            {
                "files": [{"path": "baseline.py", "responsibility": "baseline"}],
                "dependency_order": ["baseline.py"],
                "entry_points": ["baseline.py"],
                "shared_state": "metrics",
                "remote_compute": None,
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


def test_completed_partial_base_is_rejected(tmp_path: Path) -> None:
    base_run = _prepare_base_run(tmp_path)
    PipelineState(base_run).mark_completed(partial=True)
    config = AutoResearchConfig.create(
        base_run=base_run,
        output=base_run / "autoresearch",
        provider=None,
        siliconflow_config=None,
    )

    with pytest.raises(RuntimeError, match="partial replication"):
        _validate_base_run(config)


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
                "research_brief": (
                    {
                        "problem": "predict an outcome",
                        "context": "clinical prediction",
                        "proposed_method": "base classifier",
                        "datasets": ["local cohort"],
                    }
                    if eligible
                    else None
                ),
            }
            Path(context["eligibility_path"]).write_text(
                json.dumps(payload), encoding="utf-8"
            )
        elif template_name.endswith("experiment_weighting/session_instructions.md"):
            Path(context["weights_path"]).write_text(
                json.dumps(
                    {
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "weight": 1.0,
                                "rationale": "Primary experiment.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("experiment_contracts/session_instructions.md"):
            Path(context["contracts_path"]).write_text(
                json.dumps(
                    {
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "baseline_entry_points": ["python baseline.py"],
                                "model_implementation_paths": ["baseline.py"],
                                "input_representation_paths": ["baseline.py"],
                                "training_paths": ["baseline.py"],
                                "integration_paths": ["baseline.py"],
                                "data_contract": "fixed cohort, split, and features",
                                "prediction_target_contract": "outcome label",
                                "input_representation_contract": "feature vector",
                                "output_contract": "risk score",
                                "training_target_contract": "binary outcome label",
                                "loss_contract": "binary cross entropy",
                                "training_contract": "existing training loop",
                                "evaluation_contract": "existing evaluation",
                                "metrics": "The evaluator computes accuracy.",
                                "primary_metric": "accuracy",
                                "metric_direction": "higher",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("idea_generation/session_instructions.md"):
            candidates_path = Path(context["candidates_path"])
            if candidates_path.is_file():
                candidate_pool = json.loads(candidates_path.read_text(encoding="utf-8"))
            else:
                candidate_pool = {
                    "next_candidate_index": 1,
                    "candidates": [],
                    "selected_candidate_ids": [],
                }
            while len(candidate_pool["candidates"]) < 6:
                candidate_index = candidate_pool["next_candidate_index"]
                candidate_id = f"C{candidate_index:04d}"
                candidate_pool["candidates"].append(
                    {
                        "candidate_id": candidate_id,
                        "problem": f"Problem {candidate_id}",
                        "methods": [f"Method {candidate_id}"],
                        "motivation": f"Motivation {candidate_id}",
                        "evidence": [
                            {
                                "source": "paper",
                                "reference": "paper section",
                                "support": "Baseline limitation.",
                            },
                            {
                                "source": "literature",
                                "reference": f"Reference {candidate_id}",
                                "support": "Method mechanism.",
                            },
                        ],
                    }
                )
                candidate_pool["next_candidate_index"] += 1
            candidate_pool["selected_candidate_ids"] = [
                candidate["candidate_id"]
                for candidate in candidate_pool["candidates"][:3]
            ]
            candidates_path.parent.mkdir(parents=True, exist_ok=True)
            candidates_path.write_text(json.dumps(candidate_pool), encoding="utf-8")
            ideas = {
                "round_index": context["round_index"],
                "ideas": [
                    {
                        "idea_id": current_id,
                        "description": "A nontrivial refinement.",
                        "motivation": "An observed modeling limitation.",
                        "provenance": [
                            {
                                "reference": "Supporting paper.",
                                "support": "The method addresses the observed limitation.",
                            }
                        ],
                    }
                    for current_id in context["idea_ids"]
                ],
            }
            Path(context["ideas_path"]).write_text(json.dumps(ideas), encoding="utf-8")
        elif template_name.endswith("codegen/session_instructions.md"):
            if idea_id.endswith("I02"):
                refinement_types = ["training_strategy"]
                new_files = []
            elif idea_id.endswith("I03"):
                refinement_types = ["input_representation"]
                new_files = ["refinement.py"]
            else:
                refinement_types = ["model"]
                new_files = ["refinement.py"]
            for new_file in new_files:
                Path(working_dir, new_file).write_text(
                    f"IDEA_ID = {idea_id!r}\n",
                    encoding="utf-8",
                )
            baseline_path = Path(working_dir, "baseline.py")
            baseline_text = baseline_path.read_text(encoding="utf-8")
            if context["repair_audit_path"]:
                baseline_text += "# repaired model selection\n"
            else:
                baseline_text += f"# integrate {idea_id}\n"
            baseline_path.write_text(baseline_text, encoding="utf-8")
            Path(context["implementation_plan_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "summary": "Add refinement.",
                        "refinement_types": refinement_types,
                        "refinement_description": "Standalone refinement.",
                        "refine_file_list": [
                            {
                                "file_path": "baseline.py",
                                "change": "Select the refinement for E1 while preserving baseline behavior.",
                            }
                        ],
                        "new_file_list": [
                            {
                                "file_path": new_file,
                                "change": "Implement the standalone refinement.",
                            }
                            for new_file in new_files
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif template_name.endswith("audit/session_instructions.md"):
            attempt = int(Path(context["audit_path"]).stem.rsplit("_", 1)[1])
            fail = idea_id.endswith("I01") and (attempt == 1 or audit_fails_twice)
            aspects = [
                "data",
                "prediction_target",
                "input_representation",
                "output",
                "training",
                "evaluation",
            ]
            Path(context["audit_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "verdict": "fail" if fail else "pass",
                        "refinement_only": not fail,
                        "scope_evidence": ["base/refinement diff"],
                        "scope_issue": "changed fixed data" if fail else None,
                        "checks": [
                            {
                                "experiment_id": "E1",
                                "aspect": aspect,
                                "verdict": "fail" if fail and index == 0 else "pass",
                                "evidence": ["base/refinement diff"],
                                "issue": "data changed" if fail and index == 0 else None,
                            }
                            for index, aspect in enumerate(aspects)
                        ],
                        "required_fixes": ["restore refinement scope"] if fail else [],
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
                        "experiments": [
                            {
                                "experiment_id": "E1",
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
                                        "command_hint": "python baseline.py --model refined",
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
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "step_outcomes": [
                                    {
                                        "step_id": step_id,
                                        "description": "step",
                                        "command_executed": "python command.py",
                                        "exit_code": 0,
                                        "stdout": "done",
                                        "stderr": "",
                                        "output_files": (
                                            [] if step_id == 1 else [str(result_path)]
                                        ),
                                        "duration_seconds": 1.0,
                                        "fixes_applied": [],
                                        "code_modified": False,
                                        "notes": "",
                                    }
                                    for step_id in (1, 2, 3)
                                ],
                            }
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
            relative_delta = delta / 0.8
            score = 4 if is_valid else -2
            Path(context["assessment_path"]).write_text(
                json.dumps(
                    {
                        "idea_id": idea_id,
                        "verdict": "valid" if is_valid else "invalid",
                        "summary": "metric comparison complete",
                        "audit_passed": True,
                        "protocol_consistent": True,
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "metric_name": "accuracy",
                                "direction": "higher",
                                "weight": 1.0,
                                "baseline_value": 0.8,
                                "refined_value": refined,
                                "absolute_delta": delta,
                                "relative_delta": relative_delta,
                                "score": score,
                                "score_rationale": (
                                    "Strong contextual improvement"
                                    if is_valid
                                    else "The refinement is worse than the replicate"
                                ),
                                "weighted_score": score,
                                "evidence_paths": [
                                    str(config.base_run / "codegen" / "codebase" / "metrics.json"),
                                    str(Path(context["experiment_dir"]) / "metrics.json"),
                                ],
                            }
                        ],
                        "weighted_score": score,
                        "threshold": config.assessment_threshold,
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
                "## 1. Base problem and research context\nclassification\n\n"
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
        refinement_path = idea_dir / "codegen" / "codebase" / "refinement.py"
        if idea_index == 2:
            assert not refinement_path.exists()
        else:
            assert f"R01-I{idea_index:02d}" in refinement_path.read_text()
        assert not (idea_dir / "codegen" / "codebase" / ".cache").exists()
    assert not (config.base_run / "codegen" / "codebase" / "refinement.py").exists()
    assert (config.output / "report" / "idea_metric_comparison.png").read_bytes().startswith(
        b"\x89PNG"
    )
    assert (config.output / "report" / "idea_status_overview.png").read_bytes().startswith(
        b"\x89PNG"
    )
    assert any("codegen_repair" in str(call[1]) for call in calls)
    candidate_pool = json.loads(
        (config.output / "idea_generation" / "candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert candidate_pool["selected_candidate_ids"] == []
    assert [candidate["candidate_id"] for candidate in candidate_pool["candidates"]] == [
        "C0004",
        "C0005",
        "C0006",
    ]

    call_count = len(calls)
    PipelineState(config.output).resume(build_autoresearch_inputs(config))
    create_autoresearch_workflow().invoke({"config": config})
    assert len(calls) == call_count

    summary_path = config.output / "rounds" / "round_001" / "round_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["ideas"][0]["reason"] = "tampered"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    PipelineState(config.output).resume(build_autoresearch_inputs(config))
    with pytest.raises(RuntimeError, match="does not match its canonical assessments"):
        create_autoresearch_workflow().invoke({"config": config})


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
    assert "round_001/ideas.json" in round_two_context["prior_rounds_json"]
    assert "round_001/round_summary.json" in round_two_context["prior_rounds_json"]
    assert "round_001/ideas/idea_01/audit/audit.json" in (
        round_two_context["prior_rounds_json"]
    )
    assert "round_001/ideas/idea_01/assessment/assessment.json" in (
        round_two_context["prior_rounds_json"]
    )
    candidate_pool = json.loads(
        (config.output / "idea_generation" / "candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert candidate_pool["next_candidate_index"] == 10
    assert [candidate["candidate_id"] for candidate in candidate_pool["candidates"]] == [
        "C0007",
        "C0008",
        "C0009",
    ]
    assert PipelineState(config.output).state["status"] == "completed"


def test_autoresearch_ineligible_stops_before_ideas(
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


def test_autoresearch_templates_render_with_strict_context(tmp_path: Path):
    path = tmp_path / "artifact"
    contracts = {
        "experiments": [
            {
                "experiment_id": "E1",
                "data_contract": "fixed cohort and split",
                "prediction_target_contract": "fixed outcome",
                "output_contract": "prediction score",
                "evaluation_contract": "frozen evaluator",
                "metrics": "The evaluator computes AUROC.",
                "primary_metric": "AUROC",
                "metric_direction": "higher",
            }
        ]
    }
    weights = {
        "experiments": [
            {
                "experiment_id": "E1",
                "weight": 1.0,
                "rationale": "only experiment",
            }
        ]
    }
    template_contexts = {
        "eligibility": {
            "paper_markdown": path,
            "eligibility_path": path,
        },
        "experiment_weighting": {
            "paper_markdown": path,
            "experiments_path": path,
            "weights_path": path,
        },
        "experiment_contracts": {
            "experiments_path": path,
            "weights_path": path,
            "codegen_plan_path": path,
            "replicate_plan_path": path,
            "base_codebase_dir": path,
            "contracts_path": path,
        },
        "idea_generation": {
            "paper_markdown": path,
            "eligibility_path": path,
            "weights_path": path,
            "contracts_path": path,
            "reproduction_report_path": path,
            "codebase_dir": path,
            "candidates_path": path,
            "prior_rounds_json": "[]",
            "round_index": 1,
            "idea_ids": ["R01-I01", "R01-I02", "R01-I03"],
            "ideas_path": path,
        },
        "codegen": {
            "idea_id": "R01-I01",
            "paper_markdown": path,
            "ideas_path": path,
            "eligibility_path": path,
            "contracts_path": path,
            "experiments_path": path,
            "base_codegen_plan_path": path,
            "base_replicate_plan_path": path,
            "base_codebase_dir": path,
            "codebase_dir": path,
            "implementation_plan_path": path,
            "repair_audit_path": None,
        },
        "audit": {
            "idea_id": "R01-I01",
            "contracts_path": path,
            "base_codebase_dir": path,
            "codebase_dir": path,
            "implementation_plan_path": path,
            "audit_path": path,
        },
        "plan": {
            "idea_id": "R01-I01",
            "contracts_path": path,
            "weights_path": path,
            "implementation_plan_path": path,
            "audit_path": path,
            "codebase_dir": path,
            "data_dir": path,
            "cloud_drive_enabled": False,
            "experiment_dir": path,
            "experiment_plan_path": path,
            "computation_provider_state_path": path,
            "contracts": contracts,
            "weights": weights,
            "gpu_info": [],
        },
        "experiment": {
            "idea_id": "R01-I01",
            "contracts_path": path,
            "experiment_plan_path": path,
            "implementation_plan_path": path,
            "audit_path": path,
            "codebase_dir": path,
            "data_dir": None,
            "cloud_drive_enabled": False,
            "command_handoff": False,
            "base_replication_log": path,
            "base_evidence_summary": path,
            "computation_provider_state_path": path,
            "experiment_log_path": path,
            "evidence_summary_path": path,
            "experiment_dir": path,
        },
        "assessment": {
            "idea_id": "R01-I01",
            "contracts_path": path,
            "weights_path": path,
            "implementation_plan_path": path,
            "audit_path": path,
            "experiment_plan_path": path,
            "experiment_log_path": path,
            "evidence_summary_path": path,
            "base_replication_log": path,
            "base_evidence_summary": path,
            "base_reproduction_report": path,
            "base_codebase_dir": path,
            "base_replication_dir": path,
            "codebase_dir": path,
            "experiment_dir": path,
            "assessment_threshold": 0.0,
            "assessment_path": path,
        },
        "report": {
            "eligibility_path": path,
            "weights_path": path,
            "contracts_path": path,
            "base_reproduction_report": path,
            "rounds_json": "[]",
            "metric_visualization_path": path,
            "status_visualization_path": path,
            "report_path": path,
        },
    }

    for name, context in template_contexts.items():
        rendered = render_prompt(
            f"autoresearch/{name}/session_instructions.md",
            tmp_path / f"{name}.md",
            **context,
        )
        assert rendered.is_file()

    plan_prompt = (tmp_path / "plan.md").read_text(encoding="utf-8")
    assert "Primary metric: `AUROC`" in plan_prompt
    assert "Metrics: The evaluator computes AUROC." in plan_prompt
    assert "shape-prescriptive" in plan_prompt
    assert "no pre-authorized reductions" in plan_prompt
    assert "Never include or rerun an old existing or replicated baseline" in plan_prompt
    assert "Assume that replication intermediates were not saved" in plan_prompt

    codegen_prompt = (tmp_path / "codegen.md").read_text(encoding="utf-8")
    assert "Treat replication intermediates as unavailable by default" in codegen_prompt

    audit_prompt = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "Treat all replication intermediates as absent" in audit_prompt

    weighting_prompt = (tmp_path / "experiment_weighting.md").read_text(
        encoding="utf-8"
    )
    assert "only its strict prediction experiments" in weighting_prompt
    contracts_prompt = (tmp_path / "experiment_contracts.md").read_text(
        encoding="utf-8"
    )
    assert "one compact sentence, not a JSON" in contracts_prompt


def test_autoresearch_plan_cloud_pull_handoff_resumes_same_codex_session(
    tmp_path: Path,
    monkeypatch,
):
    config = AutoResearchConfig(
        base_run=tmp_path / "base",
        output=tmp_path / "autoresearch",
        provider="codex",
        clouddrive=True,
        computation_provider="vastai",
        drive_provider="google-drive",
        cloud_dataset="mimic-iv",
    )
    codebase_dir = tmp_path / "codebase"
    codebase_dir.mkdir()
    prompt_path = tmp_path / "plan.md"
    prompt_path.write_text("plan\n", encoding="utf-8")
    transcript_path = tmp_path / "plan.jsonl"
    calls = []
    events = []

    def fake_agent(**kwargs):
        calls.append(kwargs)
        events.append("resume-agent" if kwargs.get("resume_session_id") else "initial-agent")
        command_path = kwargs.get("output_last_message_path")
        if command_path is not None:
            command_path.write_text('{"command":"monitor"}\n', encoding="utf-8")
        return kwargs.get("resume_session_id") or "session-1"

    def fake_command(command, *, codebase_dir, log_path, result_path):
        events.append("monitor")
        result = {"command": command, "exit_code": 0, "duration_seconds": 1.0}
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setattr("medai.autoresearch.run_agent", fake_agent)
    monkeypatch.setattr("medai.autoresearch._run_agent_command", fake_command)
    monkeypatch.setattr(
        "medai.autoresearch._cloud_drive_materialization_completed",
        lambda _config: True,
    )
    monkeypatch.setattr(
        "medai.autoresearch.power_off_run_computation_instance",
        lambda _config: events.append("power-off"),
    )
    monkeypatch.setattr(
        "medai.autoresearch.render_prompt",
        lambda _template, destination, **_context: destination,
    )

    _run_plan_cloud_pull_handoff(
        config=config,
        round_index=1,
        idea_index=1,
        codebase_dir=codebase_dir,
        prompt_path=prompt_path,
        transcript_path=transcript_path,
    )

    assert len(calls) == 2
    assert calls[0].get("resume_session_id") is None
    assert calls[1]["resume_session_id"] == "session-1"
    assert events == ["initial-agent", "monitor", "power-off", "resume-agent"]


def test_autoresearch_reuses_base_cloud_inventory(tmp_path: Path):
    base_run = tmp_path / "base"
    remote_dir = base_run / "remote_compute"
    remote_dir.mkdir(parents=True)
    (remote_dir / "instance.json").write_text(
        json.dumps(
            {
                "provider": "vastai",
                "created_by_run": True,
                "released": True,
                "provider_state": {
                    "selected_offer": {
                        "gpu_name": "RTX 4090",
                        "gpu_count": 2,
                        "gpu_ram_mb": 24576,
                        "cpu_ram_mb": 65536,
                    },
                    "cloud_drive": {
                        "completed": True,
                        "drive": "google-drive",
                        "dataset": "mimic-iv",
                        "target_path": "/workspace/data/mimic-iv",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    inventory = {
        "dataset": "mimic-iv",
        "files": [{"path": "table.csv", "size": 1, "sha256": "0" * 64}],
    }
    (remote_dir / "cloud-inventory.v1.json").write_text(
        json.dumps(inventory),
        encoding="utf-8",
    )
    config = AutoResearchConfig(
        base_run=base_run,
        output=tmp_path / "autoresearch",
        provider="codex",
        clouddrive=True,
        computation_provider="vastai",
        drive_provider="google-drive",
        cloud_dataset="mimic-iv",
    )

    _copy_base_cloud_inventory(config)
    assert (
        config.output / "remote_compute" / "cloud-inventory.v1.json"
    ).read_text(encoding="utf-8") == (remote_dir / "cloud-inventory.v1.json").read_text(
        encoding="utf-8"
    )


def test_autoresearch_experiment_commands_power_cycle_before_agent_resume(
    tmp_path: Path,
    monkeypatch,
):
    config = AutoResearchConfig(
        base_run=tmp_path / "base",
        output=tmp_path / "autoresearch",
        provider="codex",
        computation_provider="vastai",
    )
    codebase_dir = tmp_path / "codebase"
    experiment_dir = tmp_path / "experiment"
    codebase_dir.mkdir()
    experiment_dir.mkdir()
    environment_dir = experiment_dir / "environment"
    environment_dir.mkdir()
    setup_path = environment_dir / "setup.sh"
    setup_path.write_text("mkdir -p \"$1\"\n", encoding="utf-8")
    (environment_dir / "environment.json").write_text(
        json.dumps({"language": "Python"}),
        encoding="utf-8",
    )
    (environment_dir / "setup.log").write_text("validated\n", encoding="utf-8")
    prompt_path = tmp_path / "experiment.md"
    prompt_path.write_text("experiment\n", encoding="utf-8")
    transcript_path = tmp_path / "experiment.jsonl"
    calls = []
    operations = []
    power_events = []
    preparation_count = 0

    def fake_agent(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            setup_path.write_text(
                "mkdir -p \"$1\"\npython -m pip install matplotlib\n",
                encoding="utf-8",
            )
        command_path = kwargs["output_last_message_path"]
        command_path.write_text(
            json.dumps(
                {
                    "operation": "remote_exec",
                    "command": f"command-{len(calls)}",
                    "remote": None,
                    "destination": None,
                }
            ),
            encoding="utf-8",
        )
        return kwargs.get("resume_session_id") or "session-1"

    def fake_operation(operation, **kwargs):
        operations.append((operation, kwargs))
        result = {
            "operation": operation.operation,
            "command": operation.command,
            "exit_code": 1 if len(operations) == 1 else 0,
            "duration_seconds": 1.0,
        }
        result_path = kwargs["result_path"]
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    validations = iter([RuntimeError("outputs missing"), ["complete"]])

    def fake_validate(*_args):
        result = next(validations)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("medai.autoresearch.run_agent", fake_agent)
    monkeypatch.setattr(
        "medai.autoresearch._run_autoresearch_provider_operation",
        fake_operation,
    )
    monkeypatch.setattr("medai.autoresearch._validate_experiment_artifacts", fake_validate)

    def fake_prepare(_config, _codebase, _experiment):
        nonlocal preparation_count
        preparation_count += 1
        power_events.append("on")
        if preparation_count == 1:
            raise _AutoResearchEnvironmentSetupError(
                "ModuleNotFoundError: No module named 'matplotlib'"
            )
        return {"remote_working_dir": "/workspace/medai/campaign/work"}

    monkeypatch.setattr(
        "medai.autoresearch._prepare_autoresearch_command_instance",
        fake_prepare,
    )
    monkeypatch.setattr(
        "medai.autoresearch.power_off_run_computation_instance",
        lambda _config: power_events.append("off"),
    )
    monkeypatch.setattr(
        "medai.autoresearch.render_prompt",
        lambda _template, destination, **_context: destination,
    )

    outputs = _run_experiment_command_handoff(
        config=config,
        round_index=1,
        idea_index=1,
        codebase_dir=codebase_dir,
        experiment_dir=experiment_dir,
        prompt_path=prompt_path,
        transcript_path=transcript_path,
        plan_path=tmp_path / "plan.json",
        log_path=tmp_path / "log.json",
        evidence_path=tmp_path / "evidence.json",
    )

    assert outputs == ["complete"]
    assert power_events == ["on", "off", "on", "off", "on", "off"]
    assert [operation.command for operation, _ in operations] == [
        "command-2",
        "command-3",
    ]
    assert all(
        kwargs["remote_working_dir"] == "/workspace/medai/campaign/work"
        for _, kwargs in operations
    )
    assert all(
        kwargs["remote_artifact_dir"]
        == "/workspace/medai/campaign/work/artifacts/R01-I01"
        for _, kwargs in operations
    )
    assert calls[0].get("resume_session_id") is None
    assert calls[1]["resume_session_id"] == "session-1"
    assert calls[2]["resume_session_id"] == "session-1"
    setup_result = json.loads(
        (experiment_dir / "commands" / "command_001_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert setup_result["exit_code"] == 1
    assert "before the requested operation ran" in setup_result[
        "artifact_validation_error"
    ]
    assert "matplotlib" in setup_path.read_text(encoding="utf-8")


def test_autoresearch_provider_operation_executes_remote_and_downloads_safely(
    tmp_path: Path,
    monkeypatch,
):
    state_path = tmp_path / "instance.json"
    state_path.write_text('{"provider":"fake"}\n', encoding="utf-8")
    adapter_script = tmp_path / "adapter.py"
    adapter_script.write_text(
        "import json, sys\n"
        "print(json.dumps(sys.argv[1:]))\n"
        "raise SystemExit(7 if sys.argv[-1].endswith('exit 7') else 0)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "medai.autoresearch.get_provider_adapter",
        lambda _provider: SimpleNamespace(
            script=adapter_script,
            action_timeouts={"exec": 60, "download": 60},
        ),
    )
    artifact_dir = tmp_path / "experiment" / "artifacts"

    exec_result = _run_autoresearch_provider_operation(
        AutoResearchCommand(
            operation="remote_exec",
            command="python main.py",
            remote=None,
            destination=None,
        ),
        state_path=state_path,
        remote_working_dir="/workspace/medai/campaign/work",
        remote_artifact_dir="/workspace/medai/campaign/work/artifacts/R01-I01",
        artifact_dir=artifact_dir,
        log_path=tmp_path / "exec.log",
        result_path=tmp_path / "exec.json",
        expected_provider="fake",
    )
    download_result = _run_autoresearch_provider_operation(
        AutoResearchCommand(
            operation="download",
            command=None,
            remote="results/metrics.json",
            destination="E1/metrics.json",
        ),
        state_path=state_path,
        remote_working_dir="/workspace/medai/campaign/work",
        remote_artifact_dir="/workspace/medai/campaign/work/artifacts/R01-I01",
        artifact_dir=artifact_dir,
        log_path=tmp_path / "download.log",
        result_path=tmp_path / "download.json",
        expected_provider="fake",
    )
    failed_result = _run_autoresearch_provider_operation(
        AutoResearchCommand(
            operation="remote_exec",
            command="exit 7",
            remote=None,
            destination=None,
        ),
        state_path=state_path,
        remote_working_dir="/workspace/medai/campaign/work",
        remote_artifact_dir="/workspace/medai/campaign/work/artifacts/R01-I01",
        artifact_dir=artifact_dir,
        log_path=tmp_path / "failed.log",
        result_path=tmp_path / "failed.json",
        expected_provider="fake",
    )

    exec_arguments = json.loads((tmp_path / "exec.log").read_text(encoding="utf-8"))
    assert exec_result["exit_code"] == 0
    assert exec_arguments[-4:] == [
        "--",
        "bash",
        "-lc",
        "mkdir -p -- /workspace/medai/campaign/work/artifacts/R01-I01 && "
        "cd /workspace/medai/campaign/work/codebase && "
        "export MEDAI_AUTORESEARCH_ARTIFACT_DIR="
        "/workspace/medai/campaign/work/artifacts/R01-I01 && python main.py",
    ]
    download_arguments = json.loads(
        (tmp_path / "download.log").read_text(encoding="utf-8")
    )
    assert download_result["destination"] == str(artifact_dir / "E1/metrics.json")
    assert download_arguments[-4:] == [
        "--remote",
        "/workspace/medai/campaign/work/artifacts/R01-I01/results/metrics.json",
        "--destination",
        str(artifact_dir / "E1/metrics.json"),
    ]
    assert failed_result["exit_code"] == 7


def test_autoresearch_command_schema_requires_every_nullable_field():
    schema = AutoResearchCommand.model_json_schema()

    assert set(schema["required"]) == set(schema["properties"])
    with pytest.raises(ValueError):
        AutoResearchCommand.model_validate(
            {"operation": "remote_exec", "command": "python main.py"}
        )


@pytest.mark.parametrize(
    ("remote", "destination"),
    [
        ("../data/raw.csv", "raw.csv"),
        ("results/metrics.json", "../metrics.json"),
    ],
)
def test_autoresearch_download_rejects_paths_outside_owned_roots(
    tmp_path: Path,
    monkeypatch,
    remote: str,
    destination: str,
):
    state_path = tmp_path / "instance.json"
    state_path.write_text('{"provider":"fake"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "medai.autoresearch.get_provider_adapter",
        lambda _provider: SimpleNamespace(
            script=tmp_path / "unused.py",
            action_timeouts={"download": 60},
        ),
    )

    with pytest.raises(RuntimeError, match="must remain inside"):
        _run_autoresearch_provider_operation(
            AutoResearchCommand(
                operation="download",
                command=None,
                remote=remote,
                destination=destination,
            ),
            state_path=state_path,
            remote_working_dir="/workspace/medai/campaign/work",
            remote_artifact_dir=(
                "/workspace/medai/campaign/work/artifacts/R01-I01"
            ),
            artifact_dir=tmp_path / "experiment" / "artifacts",
            log_path=tmp_path / "download.log",
            result_path=tmp_path / "download.json",
            expected_provider="fake",
        )


def test_autoresearch_command_instance_syncs_local_code_and_environment(
    tmp_path: Path,
    monkeypatch,
):
    output = tmp_path / "autoresearch"
    state_path = output / "remote_compute" / "instance.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": "vastai",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "remote_working_dir": "/workspace/medai/campaign/work",
                    "cloud_drive": {
                        "completed": True,
                        "drive": "google-drive",
                        "dataset": "mimic-iv",
                        "target_path": "/workspace/medai/campaign/data/mimic-iv",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    codebase_dir = tmp_path / "codebase"
    codebase_dir.mkdir()
    (codebase_dir / "model.py").write_text("pass\n", encoding="utf-8")
    experiment_dir = tmp_path / "experiment"
    environment_dir = experiment_dir / "environment"
    environment_dir.mkdir(parents=True)
    (environment_dir / "setup.sh").write_text("mkdir -p \"$1\"\n", encoding="utf-8")
    (environment_dir / "environment.json").write_text(
        json.dumps({"language": "Python", "runtime": "3.10"}),
        encoding="utf-8",
    )
    config = AutoResearchConfig(
        base_run=tmp_path / "base",
        output=output,
        provider="codex",
        clouddrive=True,
        computation_provider="vastai",
        drive_provider="google-drive",
        cloud_dataset="mimic-iv",
    )
    actions = []
    setup_failure = False
    monkeypatch.setattr(
        "medai.autoresearch.power_on_run_computation_instance",
        lambda _config: {"created": True, "materialization_required": True},
    )
    monkeypatch.setattr(
        "medai.autoresearch._cloud_drive_materialization_completed",
        lambda _config: True,
    )

    def fake_action(_state_path, action, *, arguments=None, expected_provider=None):
        actions.append((action, arguments, expected_provider))
        if setup_failure and action == "exec" and "setup.sh" in arguments[-1]:
            raise RuntimeError("ModuleNotFoundError: No module named 'matplotlib'")
        return ""

    monkeypatch.setattr(
        "medai.autoresearch._run_computation_provider_action",
        fake_action,
    )

    result = _prepare_autoresearch_command_instance(
        config,
        codebase_dir,
        experiment_dir,
    )

    assert result["created"] is True
    assert [action for action, _, _ in actions] == [
        "cloud-pull",
        "exec",
        "upload",
        "upload",
        "exec",
    ]
    assert actions[2][1] == [
        "--source",
        str(codebase_dir),
        "--remote",
        "/workspace/medai/campaign/work/.codebase.next",
    ]
    assert actions[3][1] == [
        "--source",
        str(environment_dir),
        "--remote",
        "/workspace/medai/campaign/work/.environment-spec.next",
    ]
    first_validation = json.loads(
        (environment_dir / "validation.json").read_text(encoding="utf-8")
    )
    assert _mother_environment_validated(experiment_dir) is True

    (environment_dir / "setup.sh").write_text(
        "mkdir -p \"$1\"\npython -m pip install matplotlib\n",
        encoding="utf-8",
    )
    assert _mother_environment_validated(experiment_dir) is False

    setup_failure = True
    actions.clear()
    with pytest.raises(_AutoResearchEnvironmentSetupError, match="matplotlib"):
        _prepare_autoresearch_command_instance(config, codebase_dir, experiment_dir)
    assert _mother_environment_validated(experiment_dir) is False

    setup_failure = False
    actions.clear()
    _prepare_autoresearch_command_instance(config, codebase_dir, experiment_dir)
    second_validation = json.loads(
        (environment_dir / "validation.json").read_text(encoding="utf-8")
    )
    assert second_validation["setup_sha256"] != first_validation["setup_sha256"]
    assert _mother_environment_validated(experiment_dir) is True


def test_idea_artifact_rejects_wrong_ids_or_fields():
    valid = {
        "round_index": 1,
        "ideas": [
            {
                "idea_id": idea_id,
                "description": "refinement",
                "motivation": "observation",
                "provenance": [{"reference": "paper", "support": "mechanism"}],
            }
            for idea_id in ("R01-I01", "R01-I02", "R01-I03")
        ],
    }
    IdeaGenerationArtifact.model_validate(valid)

    with pytest.raises(ValueError, match="does not match round 2"):
        validate_idea_generation_artifact(
            IdeaGenerationArtifact.model_validate(valid),
            2,
        )

    wrong_id = json.loads(json.dumps(valid))
    wrong_id["ideas"][2]["idea_id"] = "R01-I04"
    with pytest.raises(ValueError, match="exactly these IDs"):
        IdeaGenerationArtifact.model_validate(wrong_id)

    extra_field = json.loads(json.dumps(valid))
    extra_field["ideas"][0]["extra"] = "not allowed"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        IdeaGenerationArtifact.model_validate(extra_field)


def test_base_fingerprint_includes_paper_artifacts(tmp_path: Path):
    base_run = _prepare_base_run(tmp_path)
    config = AutoResearchConfig.create(
        base_run=base_run,
        output=base_run / "autoresearch",
        provider=None,
        siliconflow_config=None,
    )
    before = build_autoresearch_inputs(config)["base_artifact_fingerprint"]
    (base_run / "preprocessing" / "artifacts" / "table.csv").write_text(
        "metric,value\naccuracy,0.8\n",
        encoding="utf-8",
    )
    after = build_autoresearch_inputs(config)["base_artifact_fingerprint"]
    assert after != before
