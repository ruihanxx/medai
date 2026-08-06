import json
from pathlib import Path

import pytest

from medai.config import RunConfig
from medai.models import CodegenPlan
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.workflow import (
    create_workflow,
    power_off_run_computation_instance,
    preflight_node,
    prepare_replication_resume,
    release_run_computation_instance,
    replicate_agent_node,
    resolve_replication_output,
    validate_codegen_remote_compute,
)


def _replicate_config(tmp_path: Path) -> RunConfig:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "data"
    data.mkdir()
    return RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data=data,
        siliconflow_config=None,
    )


def _write_remote_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "old-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )


def _write_codegen_plan(path: Path, remote_state_path: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    remote_compute = None
    if remote_state_path is not None:
        remote_compute = {
            "state_path": str(remote_state_path),
            "remote_working_dir": "/remote/run",
            "remote_dataset_dir": "/remote/data",
        }
    path.write_text(
        json.dumps(
            {
                "files": [{"path": "run.py", "responsibility": "Run"}],
                "dependency_order": ["run.py"],
                "entry_points": ["run.py"],
                "shared_state": "None",
                "ambiguities": [],
                "remote_compute": remote_compute,
            }
        ),
        encoding="utf-8",
    )


def _write_replication_log(path: Path, output_file: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "step_outcomes": [
                    {
                        "step_id": 1,
                        "description": "run",
                        "command_executed": "python run.py",
                        "exit_code": 0,
                        "stdout": "ok",
                        "stderr": "",
                        "output_files": [output_file],
                        "duration_seconds": 1,
                        "fixes_applied": [],
                        "code_modified": False,
                        "notes": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_cloud_drive_preflight_accepts_remote_only_data(
    tmp_path: Path, monkeypatch
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("AUTODL_TOKEN", "token")
    monkeypatch.setenv("AUTODL_IMAGE_UUID", "image")
    monkeypatch.setenv("AUTODL_AUTOPANEL_PASSWORD", "password")
    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data="mimic-iv",
        siliconflow_config=None,
        clouddrive=True,
    )
    PipelineState.create(config.output, {"paper": str(paper), "clouddrive": True})
    monkeypatch.setattr(
        "medai.workflow.detect_resources",
        lambda output: {"cpu_count": 1, "gpus": []},
    )

    result = preflight_node({"config": config})

    assert Path(result["resources_path"]).is_file()
    assert PipelineState(config.output).is_stage_completed("preflight")


def test_codegen_remote_compute_requires_only_static_paths(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    remote_compute = {
        "state_path": str(state_path),
        "remote_working_dir": "/remote/run",
        "remote_dataset_dir": "/remote/data",
        "provider": "example-provider",
        "selection_rationale": "Selected by the provider procedure.",
    }
    payload = {
        "files": [{"path": "run.py", "responsibility": "Run"}],
        "dependency_order": ["run.py"],
        "entry_points": ["run.py"],
        "shared_state": "None",
        "ambiguities": [],
        "remote_compute": remote_compute,
    }
    plan = CodegenPlan.model_validate(payload)

    assert plan.remote_compute is not None
    assert plan.remote_compute.model_dump()["selection_rationale"].startswith("Selected")
    validate_codegen_remote_compute(plan, state_path)

    for field in ("state_path", "remote_working_dir", "remote_dataset_dir"):
        missing = {
            **payload,
            "remote_compute": {k: v for k, v in remote_compute.items() if k != field},
        }
        with pytest.raises(ValueError, match=field):
            CodegenPlan.model_validate(missing)

    mismatched = CodegenPlan.model_validate(
        {
            **payload,
            "remote_compute": {
                **remote_compute,
                "state_path": str(tmp_path / "other" / "instance.json"),
            },
        }
    )
    with pytest.raises(RuntimeError, match="does not match the current run"):
        validate_codegen_remote_compute(mismatched, state_path)


def test_cloud_remote_compute_requires_completed_matching_active_state(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    state_path.parent.mkdir(parents=True)
    target = "/root/autodl-tmp/medai/mimic-iv"
    remote_compute = {
        "state_path": str(state_path),
        "remote_working_dir": "/root/autodl-tmp/medai-run",
        "remote_dataset_dir": target,
    }
    plan = CodegenPlan.model_validate(
        {
            "files": [{"path": "run.py", "responsibility": "Run"}],
            "dependency_order": ["run.py"],
            "entry_points": ["run.py"],
            "shared_state": "None",
            "ambiguities": [],
            "remote_compute": remote_compute,
        }
    )
    envelope = {
        "provider": "autodl",
        "created_by_run": True,
        "released": False,
        "provider_state": {
            "instance_uuid": "instance",
            "cloud_drive": {
                "status": "completed",
                "provider": "aliyun",
                "dataset": "mimic-iv",
                "target_path": target,
            },
        },
    }
    state_path.write_text(json.dumps(envelope), encoding="utf-8")

    cloud = validate_codegen_remote_compute(
        plan,
        state_path,
        cloud_dataset="mimic-iv",
        drive_provider="aliyun",
    )
    assert cloud is not None and cloud["target_path"] == target

    envelope["provider_state"]["cloud_drive"]["status"] = "downloading"
    state_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete or inconsistent"):
        validate_codegen_remote_compute(
            plan,
            state_path,
            cloud_dataset="mimic-iv",
            drive_provider="aliyun",
        )

    envelope["provider_state"]["cloud_drive"]["status"] = "completed"
    envelope["released"] = True
    state_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(RuntimeError, match="already released"):
        validate_codegen_remote_compute(
            plan,
            state_path,
            cloud_dataset="mimic-iv",
            drive_provider="aliyun",
        )
    validate_codegen_remote_compute(
        plan,
        state_path,
        cloud_dataset="mimic-iv",
        drive_provider="aliyun",
        require_active=False,
    )


def test_full_workflow_with_fake_agents(tmp_path: Path, monkeypatch, capsys):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("source", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=repo,
        data=data,
        siliconflow_config=None,
    )
    PipelineState.create(output, {"paper": str(paper), "provider": "codex"})
    transcript_paths = []

    def fake_convert(paper_path, preprocessing_dir):
        preprocessing_dir.mkdir(parents=True, exist_ok=True)
        (preprocessing_dir / "artifacts").mkdir()
        markdown = preprocessing_dir / "paper.md"
        markdown.write_text("# Paper", encoding="utf-8")
        return markdown

    def fake_agent(*, prompt_path, working_dir, **kwargs):
        transcript_path = kwargs["transcript_path"]
        transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
        transcript_paths.append(transcript_path.relative_to(output).as_posix())
        name = prompt_path.name
        if name == "preprocessing.md":
            (output / "preprocessing" / "claims.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "C1",
                                "statement": "Accuracy is reported.",
                                "role": "validation",
                                "kind": "numeric",
                                "paper_result": 0.9,
                                "provenance": {
                                    "page": 1,
                                    "section": "Results",
                                    "quote": "Accuracy was 0.9.",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output / "preprocessing" / "experiment_todo.json").write_text(
                json.dumps(
                    {
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "description": "Train and evaluate.",
                                "computational_demand": "The experiment needs the paper's stated GPU and memory capacity.",
                                "claims": ["C1"],
                                "artifacts": ["Figure 1"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif name == "codegen.md":
            (output / "codegen" / "codebase" / "codegen_plan.json").write_text(
                json.dumps(
                    {
                        "files": [{"path": "run.py", "responsibility": "Run experiment"}],
                        "dependency_order": ["run.py"],
                        "entry_points": ["run.py"],
                        "shared_state": "Files",
                        "remote_compute": None,
                        "ambiguities": [
                            {
                                "question": "The batch size is unspecified.",
                                "assumption": "Use batch size 32.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif name == "audit_attempt_001.md":
            (working_dir / "audit_report.md").write_text(
                "# Preprocessing Audit Report\n\n"
                "## Scope\n\nFull local preprocessing.\n\n"
                "## Paper expectations\n\nOne binary target.\n\n"
                "## Commands executed\n\n`python preprocess.py`\n\n"
                "## Observed statistics\n\nBoth classes remain.\n\n"
                "## Sanity assessment\n\nNo significant issue.\n\n"
                "## Limitations\n\nNone.\n\n"
                "## Required codegen changes\n\nNone.\n\n"
                "Verdict: PASS\n",
                encoding="utf-8",
            )
        elif name == "plan.md":
            (output / "plan" / "replicate_plan.json").write_text(
                json.dumps(
                    {
                        "environment": {
                            "language": "Python",
                            "key_dependencies": [],
                            "setup_hints": "Use the local CPU.",
                        },
                        "steps": [
                            {
                                "id": 1,
                                "description": "Prepare the environment.",
                                "command_hint": "python --version",
                                "expected_outcome": "Prints a Python version.",
                                "verifies": [],
                            },
                            {
                                "id": 2,
                                "description": "Run evaluation.",
                                "command_hint": "python run.py",
                                "expected_outcome": "Writes metrics.json.",
                                "verifies": ["C1"],
                            },
                            {
                                "id": 3,
                                "description": "Render the figure.",
                                "command_hint": "python plot.py",
                                "expected_outcome": "Writes figure.png.",
                                "verifies": ["Figure 1"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif name == "replicate.md":
            result_dir = output / "replication" / "E1"
            result_dir.mkdir(parents=True)
            (result_dir / "figure.png").write_bytes(b"png")
            (result_dir / "metrics.json").write_text(
                '{"accuracy": 0.89}\n', encoding="utf-8"
            )
            (output / "replication" / "replication_log.json").write_text(
                json.dumps(
                    {
                        "step_outcomes": [
                            {
                                "step_id": 1,
                                "description": "Prepare the environment.",
                                "command_executed": "python --version",
                                "exit_code": 0,
                                "stdout": "Python 3.11",
                                "stderr": "",
                                "output_files": [],
                                "duration_seconds": 0.1,
                                "fixes_applied": [],
                                "code_modified": False,
                                "notes": "",
                            },
                            {
                                "step_id": 2,
                                "description": "Run evaluation.",
                                "command_executed": "python run.py",
                                "exit_code": 0,
                                "stdout": "accuracy=0.89",
                                "stderr": "",
                                "output_files": ["replication/E1/metrics.json"],
                                "duration_seconds": 1.0,
                                "fixes_applied": [],
                                "code_modified": False,
                                "notes": "",
                            },
                            {
                                "step_id": 3,
                                "description": "Render the figure.",
                                "command_executed": "python plot.py",
                                "exit_code": 0,
                                "stdout": "wrote figure.png",
                                "stderr": "",
                                "output_files": ["replication/E1/figure.png"],
                                "duration_seconds": 1.0,
                                "fixes_applied": [],
                                "code_modified": False,
                                "notes": "",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output / "replication" / "evidence_summary.json").write_text(
                json.dumps(
                    {
                        "environment": {
                            "python_version": "3.11",
                            "gpu_available": False,
                            "gpu_model": None,
                            "key_packages": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
        elif name == "report_E1.md":
            (output / "report" / "reproduction_report.md").write_text(
                "# Reproduction Report\n\n"
                "## 1. Per-experiment reports\n\n"
                "### E1\n\nC1 compares 0.9 with 0.89. Figure 1 was reproduced.\n\n"
                "## 2. Validation claim assessment\n\n"
                "C1: close (1.1% relative error).\n\n"
                "## 3. Replication risk list\n\n"
                "The batch size is unspecified. Assumption: Use batch size 32.\n",
                encoding="utf-8",
            )

    monkeypatch.setattr("medai.workflow.convert_pdf_to_markdown", fake_convert)
    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    monkeypatch.setattr(
        "medai.workflow.detect_resources",
        lambda path: {"cpu": {}, "memory": {}, "disk": {}, "gpus": []},
    )

    result = create_workflow().invoke({"config": config})

    stage_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("enter ")
    ]
    assert stage_lines == [
        "enter preflight stage",
        "enter preprocessing stage",
        "enter preprocessing agent stage",
        "enter codegen stage",
        "enter audit agent stage",
        "enter plan stage",
        "enter replicate stage",
        "enter report stage",
    ]
    assert Path(result["report_path"]).is_file()
    assert transcript_paths == [
        "preprocessing/preprocessing_transcript.jsonl",
        "codegen/codegen_transcript.jsonl",
        "codegen/audit/attempt_001/audit_transcript.jsonl",
        "plan/plan_transcript.jsonl",
        "replication/replication_transcript.jsonl",
        "report/E1_transcript.jsonl",
    ]
    assert (output / "codegen" / "codebase" / "README.md").is_file()
    dataset_patch_path = output / "system_maintenance" / "dataset" / "patch.json"
    assert json.loads(dataset_patch_path.read_text(encoding="utf-8")) == []
    skill_corrections_path = output / "system_maintenance" / "skills" / "corrections.json"
    assert json.loads(skill_corrections_path.read_text(encoding="utf-8")) == []
    codegen_prompt = (output / "prompts" / "codegen.md").read_text(encoding="utf-8")
    assert str(dataset_patch_path) in codegen_prompt
    assert str(skill_corrections_path) in codegen_prompt
    assert '"file name": "dataset_graph.yaml"' in codegen_prompt
    assert "/explore-data/" not in codegen_prompt
    audit_prompt = (output / "prompts" / "audit_attempt_001.md").read_text(
        encoding="utf-8"
    )
    assert str(data) in audit_prompt
    assert "Do not connect to, query, stop, release" in audit_prompt
    assert "Run the complete preprocessing locally" in audit_prompt
    plan_prompt = (output / "prompts" / "plan.md").read_text(encoding="utf-8")
    assert '"environment"' in plan_prompt
    assert '"command_hint"' in plan_prompt
    assert '"verifies"' in plan_prompt
    replication_prompt = (output / "prompts" / "replicate.md").read_text(
        encoding="utf-8"
    )
    assert "replication_log.json" in replication_prompt
    assert "evidence_summary.json" in replication_prompt
    report_prompt = (output / "prompts" / "report_E1.md").read_text(encoding="utf-8")
    assert str(output / "plan" / "replicate_plan.json") in report_prompt
    assert "replication_log.json" in report_prompt
    assert "evidence_summary.json" in report_prompt
    assert "result.json" not in report_prompt
    assert "## 1. Per-experiment reports" in report_prompt
    assert "## 2. Validation claim assessment" in report_prompt
    assert "## 3. Replication risk list" in report_prompt
    assert "The batch size is unspecified." in report_prompt
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert list(manifest["stages"]) == [
        "preflight",
        "preprocess_pdf",
        "preprocessing_agent",
        "codegen_agent",
        "audit_agent",
        "plan_agent",
        "replicate_agent",
        "report_agents",
    ]

    resumed = create_workflow().invoke({"config": config})
    resumed_lines = capsys.readouterr().out.splitlines()
    assert not [line for line in resumed_lines if line.startswith("enter ")]
    assert len([line for line in resumed_lines if line.startswith("resume ")]) == 8
    assert Path(resumed["report_path"]) == output / "report" / "reproduction_report.md"
    assert len(transcript_paths) == 6


def test_replication_outputs_stay_inside_run_roots(tmp_path: Path):
    codebase = tmp_path / "codebase"
    replication = tmp_path / "replication"
    codebase.mkdir()
    replication.mkdir()
    evidence = replication / "E1" / "metrics.json"
    evidence.parent.mkdir()
    evidence.write_text("{}\n", encoding="utf-8")

    assert resolve_replication_output("E1/metrics.json", codebase, replication) == evidence
    package_dir = codebase / "output" / "R" / "library" / "duckdb"
    package_dir.mkdir(parents=True)
    assert resolve_replication_output(str(package_dir), codebase, replication) == package_dir
    previous_mount = tmp_path / "old-mount" / "replication" / "E1" / "metrics.json"
    assert resolve_replication_output(str(previous_mount), codebase, replication) == evidence
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="inside the copied codebase"):
        resolve_replication_output(str(outside), codebase, replication)


def test_smart_replicate_injects_anchors_and_requires_round_log(
    tmp_path: Path,
    monkeypatch,
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    (output / "prompts").mkdir()
    (output / "replication").mkdir()
    PipelineState.create(output, {"paper": str(paper), "provider": "codex"})
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
        smart_replicate=True,
    )
    claims_path = output / "preprocessing" / "claims.json"
    claims_path.parent.mkdir()
    claims_path.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "claim_id": "C1",
                        "statement": "Accuracy is reported.",
                        "role": "final",
                        "kind": "numeric",
                        "paper_result": 0.9,
                        "provenance": {
                            "page": 1,
                            "section": "Results",
                            "quote": "Accuracy was 0.9.",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    experiments_path = output / "preprocessing" / "experiment_todo.json"
    experiments_path.write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "experiment_id": "E1",
                        "description": "Train and evaluate.",
                        "computational_demand": "The experiment needs the paper's stated GPU and memory capacity.",
                        "claims": ["C1"],
                        "artifacts": ["Figure 1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    replicate_plan_path = output / "plan" / "replicate_plan.json"
    replicate_plan_path.parent.mkdir()
    replicate_plan_path.write_text(
        json.dumps(
            {
                "environment": {
                    "language": "Python",
                    "key_dependencies": [],
                    "setup_hints": "Use the local CPU.",
                },
                "steps": [
                    {
                        "id": 1,
                        "description": "Prepare.",
                        "command_hint": "python --version",
                        "expected_outcome": "Prints version.",
                        "verifies": [],
                    },
                    {
                        "id": 2,
                        "description": "Run.",
                        "command_hint": "python run.py",
                        "expected_outcome": "Writes metrics.",
                        "verifies": ["C1"],
                    },
                    {
                        "id": 3,
                        "description": "Render.",
                        "command_hint": "python plot.py",
                        "expected_outcome": "Writes figure.",
                        "verifies": ["Figure 1"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_agent(*, prompt_path, transcript_path, **kwargs):
        transcript_path.write_text('{"type":"done"}\n', encoding="utf-8")
        result_dir = output / "replication" / "E1"
        result_dir.mkdir()
        artifact_path = result_dir / "figure.png"
        artifact_path.write_bytes(b"png")
        (output / "replication" / "replication_log.json").write_text(
            json.dumps(
                {
                    "step_outcomes": [
                        {
                            "step_id": step_id,
                            "description": "Run step.",
                            "command_executed": "python run.py",
                            "exit_code": 0,
                            "stdout": "done",
                            "stderr": "",
                            "output_files": [] if step_id == 1 else [str(artifact_path)],
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
        (output / "replication" / "evidence_summary.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "python_version": "3.11",
                        "gpu_available": False,
                        "gpu_model": None,
                        "key_packages": {},
                    }
                }
            ),
            encoding="utf-8",
        )
        (result_dir / "smart_replicate_log.json").write_text(
            json.dumps(
                {
                    "experiment_id": "E1",
                    "baseline_result": 0.88,
                    "anchors": {"C1": 0.9},
                    "rounds": [
                        {
                            "round": 1,
                            "observed_result": 0.88,
                            "anchor_comparison": "0.02 below anchor",
                            "hypothesis": "NA rows should be excluded",
                            "changes": ["Exclude NA rows before evaluation"],
                            "commands": ["python run.py"],
                            "result_after_change": 0.89,
                            "conclusion": "supported",
                        }
                    ],
                    "final_result": 0.89,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    replicate_agent_node(
        {
            "config": config,
            "claims_path": str(claims_path),
            "experiments_path": str(experiments_path),
            "replicate_plan_path": str(replicate_plan_path),
            "codebase_dir": str(codebase),
        }
    )

    prompt = (output / "prompts" / "replicate.md").read_text(encoding="utf-8")
    assert "Smart Replicate is enabled" in prompt
    assert '"anchor": 0.9' in prompt
    assert "five adjustment rounds per experiment" in prompt


def test_cloud_replicate_pulls_before_agent_and_powers_off_after_validation(
    tmp_path: Path,
    monkeypatch,
):
    import medai.workflow as workflow

    base = _replicate_config(tmp_path)
    config = RunConfig(
        paper=base.paper,
        output=base.output,
        provider=base.provider,
        clouddrive=True,
        drive_provider="aliyun",
        cloud_dataset="mimic-iv",
    )
    PipelineState.create(config.output, {"provider": "codex"})
    plan = workflow.ReplicationPlan.model_validate(
        {
            "environment": {
                "language": "Python",
                "key_dependencies": [],
                "setup_hints": "remote",
            },
            "steps": [
                {
                    "id": step_id,
                    "description": f"step {step_id}",
                    "command_hint": "python run.py",
                    "expected_outcome": "output",
                    "verifies": [],
                }
                for step_id in (1, 2, 3)
            ],
        }
    )
    claims = workflow.ClaimsFile.model_validate(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "statement": "Accuracy is reported.",
                    "role": "final",
                    "kind": "numeric",
                    "paper_result": 0.9,
                    "provenance": {
                        "page": 1,
                        "section": "Results",
                        "quote": "Accuracy was 0.9.",
                    },
                }
            ]
        }
    )
    experiments = workflow.ExperimentTodo.model_validate(
        {
            "experiments": [
                {
                    "experiment_id": "E1",
                    "description": "Train and evaluate.",
                    "computational_demand": "GPU",
                    "claims": ["C1"],
                    "artifacts": [],
                }
            ]
        }
    )
    models = {
        workflow.ReplicationPlan: plan,
        workflow.ClaimsFile: claims,
        workflow.ExperimentTodo: experiments,
    }
    events = []

    def fake_render(_template, destination, **_context):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("prompt", encoding="utf-8")
        return destination

    monkeypatch.setattr(workflow, "load_model", lambda _path, model: models[model])
    monkeypatch.setattr(workflow, "validate_codegen_remote_compute", lambda *_a, **_k: None)
    monkeypatch.setattr(workflow, "render_prompt", fake_render)
    monkeypatch.setattr(workflow, "_cloud_pull", lambda _config: events.append("cloud-pull"))
    monkeypatch.setattr(workflow, "run_agent", lambda **_kwargs: events.append("agent"))
    monkeypatch.setattr(
        workflow,
        "validate_replication_artifacts",
        lambda _state: events.append("validate-artifacts") or [],
    )
    monkeypatch.setattr(
        workflow,
        "power_off_run_computation_instance",
        lambda _config: events.append("power-off"),
    )

    replicate_agent_node(
        {
            "config": config,
            "claims_path": "claims.json",
            "experiments_path": "experiments.json",
            "replicate_plan_path": "replicate_plan.json",
            "codebase_dir": str(config.output / "codegen" / "codebase"),
        }
    )

    assert events == ["cloud-pull", "agent", "validate-artifacts", "power-off"]


def test_graph_stops_after_a_stage_failure(monkeypatch):
    import medai.workflow as workflow

    calls = []

    def succeeds(state):
        calls.append("preflight")
        return {}

    def fails(state):
        calls.append("preprocess_pdf")
        raise RuntimeError("stop")

    def must_not_run(state):
        calls.append("unexpected")
        return {}

    monkeypatch.setattr(workflow, "preflight_node", succeeds)
    monkeypatch.setattr(workflow, "preprocess_pdf_node", fails)
    monkeypatch.setattr(workflow, "preprocessing_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "codegen_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "audit_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "plan_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "replicate_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "report_agents_node", must_not_run)

    with pytest.raises(RuntimeError, match="stop"):
        workflow.create_workflow().invoke({"config": object()})
    assert calls == ["preflight", "preprocess_pdf"]


def test_graph_routes_failed_audit_back_to_codegen_once(monkeypatch):
    import medai.workflow as workflow

    calls = []
    audit_verdicts = iter(["FAIL", "PASS"])

    def stage(name, result=None):
        def run(state):
            calls.append(name)
            return result or {}

        return run

    def audit(state):
        calls.append("audit_agent")
        return {"audit_verdict": next(audit_verdicts)}

    monkeypatch.setattr(workflow, "preflight_node", stage("preflight"))
    monkeypatch.setattr(workflow, "preprocess_pdf_node", stage("preprocess_pdf"))
    monkeypatch.setattr(
        workflow, "preprocessing_agent_node", stage("preprocessing_agent")
    )
    monkeypatch.setattr(workflow, "codegen_agent_node", stage("codegen_agent"))
    monkeypatch.setattr(workflow, "audit_agent_node", audit)
    monkeypatch.setattr(workflow, "plan_agent_node", stage("plan_agent"))
    monkeypatch.setattr(workflow, "replicate_agent_node", stage("replicate_agent"))
    monkeypatch.setattr(workflow, "report_agents_node", stage("report_agents"))

    workflow.create_workflow().invoke({"config": object()})

    assert calls == [
        "preflight",
        "preprocess_pdf",
        "preprocessing_agent",
        "codegen_agent",
        "audit_agent",
        "codegen_agent",
        "audit_agent",
        "plan_agent",
        "replicate_agent",
        "report_agents",
    ]


def test_codegen_remote_computation_routes_through_generic_skill(tmp_path: Path):
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        tmp_path / "codegen.md",
        codebase_dir=tmp_path / "codebase",
        paper_markdown=tmp_path / "paper.md",
        claims_path=tmp_path / "claims.json",
        experiments_path=tmp_path / "experiments.json",
        data_dir=None,
        skills_dir=Path("/skills"),
        resources_path=tmp_path / "resources.json",
        codegen_plan_path=tmp_path / "codegen_plan.json",
        dataset_patch_path=tmp_path / "patch.json",
        skill_corrections_path=tmp_path / "corrections.json",
        computation_provider_state_path=tmp_path / "instance.json",
        gpu_info=[],
        computation_provider="AutoDL",
        resuming=False,
    )

    prompt = prompt_path.read_text(encoding="utf-8")
    assert "/skills/computation_provider/SKILL.md" in prompt
    assert str(tmp_path / "instance.json") in prompt
    assert "autodl" not in prompt.lower()


def test_codegen_cloud_drive_forces_remote_materialization_before_inspection(
    tmp_path: Path,
):
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        tmp_path / "cloud-codegen.md",
        codebase_dir=tmp_path / "codebase",
        paper_markdown=tmp_path / "paper.md",
        claims_path=tmp_path / "claims.json",
        experiments_path=tmp_path / "experiments.json",
        data_dir=None,
        cloud_drive_enabled=True,
        cloud_dataset="mimic-iv",
        drive_provider="aliyun",
        cloud_source="medai/mimic-iv",
        cloud_replacement_required=True,
        skills_dir=Path("/skills"),
        codegen_plan_path=tmp_path / "codegen_plan.json",
        dataset_patch_path=tmp_path / "patch.json",
        skill_corrections_path=tmp_path / "corrections.json",
        computation_provider_state_path=tmp_path / "instance.json",
        gpu_info=[],
        computation_provider="AutoDL",
        resuming=True,
        audit_feedback_path=None,
    )

    prompt = prompt_path.read_text(encoding="utf-8")
    assert "Cloud-backed data makes remote computation mandatory" in prompt
    assert "Before inspecting dataset documentation, schema, metadata, or content" in prompt
    assert "mimic-iv" in prompt
    assert "Create at most one replacement" in prompt
    assert "Never copy\nraw cloud data into the local run" in prompt


def test_codegen_prompt_resolves_paper_omissions_before_implementation(tmp_path: Path):
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        tmp_path / "codegen.md",
        codebase_dir=tmp_path / "codebase",
        paper_markdown=tmp_path / "paper.md",
        claims_path=tmp_path / "claims.json",
        experiments_path=tmp_path / "experiments.json",
        data_dir=None,
        skills_dir=Path("/skills"),
        resources_path=tmp_path / "resources.json",
        codegen_plan_path=tmp_path / "codegen_plan.json",
        dataset_patch_path=tmp_path / "patch.json",
        skill_corrections_path=tmp_path / "corrections.json",
        computation_provider_state_path=tmp_path / "instance.json",
        gpu_info=[],
        computation_provider=None,
        resuming=False,
    )

    prompt = prompt_path.read_text(encoding="utf-8")
    resolution_heading = "### 2.4. Resolve paper omissions before implementation"
    assert resolution_heading in prompt
    assert prompt.index(resolution_heading) < prompt.index("### 2.5. Capture the plan to disk")
    assert "Widely accepted medical knowledge and standard medical-research methods" in prompt
    assert "do not leave a TODO,\nsilently apply a library default" in prompt
    assert "where that\nchoice is implemented" in prompt


def test_resume_archives_interrupted_replicate_attempt_and_restarts_it(
    tmp_path: Path,
    monkeypatch,
):
    config = _replicate_config(tmp_path)
    state = PipelineState.create(config.output, {"provider": "codex"})
    codebase = config.output / "codegen" / "codebase"
    _write_codegen_plan(codebase / "codegen_plan.json")
    referenced_output = codebase / "results" / "metrics.json"
    referenced_output.parent.mkdir(parents=True)
    referenced_output.write_text('{"score": 0.9}', encoding="utf-8")
    _write_replication_log(
        config.output / "replication" / "replication_log.json",
        str(referenced_output),
    )
    (config.output / "replication" / "old.txt").write_text("old", encoding="utf-8")
    (config.output / "report").mkdir(parents=True)
    (config.output / "report" / "reproduction_report.md").write_text(
        "old report", encoding="utf-8"
    )
    (config.output / "prompts").mkdir(parents=True)
    (config.output / "prompts" / "replicate.md").write_text(
        "old replicate prompt", encoding="utf-8"
    )
    (config.output / "prompts" / "report_E1.md").write_text(
        "old report prompt", encoding="utf-8"
    )
    remote_state_path = config.output / "remote_compute" / "instance.json"
    _write_remote_state(remote_state_path)
    state.start_stage("replicate_agent")
    state.complete_stage("replicate_agent", ["old"])
    state.start_stage("report_agents")
    state.fail("interrupted")
    state.resume({"provider": "codex"})
    monkeypatch.setattr(
        "medai.workflow.reconcile_run_computation_instance",
        lambda _config: {
            "replaced": False,
            "instance_uuid": "old-instance",
            "status": "running",
        },
    )

    result = prepare_replication_resume(config)

    archive = config.output / "resume_history" / "resume_001"
    assert result["rollback"] == "replicate"
    assert result["archive"] == str(archive)
    assert (archive / "replication" / "old.txt").read_text(encoding="utf-8") == "old"
    assert (
        archive / "report" / "reproduction_report.md"
    ).read_text(encoding="utf-8") == "old report"
    assert (archive / "prompts" / "replicate.md").is_file()
    assert (archive / "prompts" / "report_E1.md").is_file()
    copied_output = archive / "referenced_codebase_outputs" / "results" / "metrics.json"
    assert copied_output.read_text(encoding="utf-8") == '{"score": 0.9}'
    mapping = json.loads((archive / "path_mapping.json").read_text(encoding="utf-8"))
    assert mapping["referenced_codebase_outputs"][0]["original_path"] == str(
        referenced_output
    )
    assert mapping["referenced_codebase_outputs"][0]["archived_path"] == str(
        copied_output
    )
    assert list((config.output / "replication").iterdir()) == []
    assert list((config.output / "report").iterdir()) == []
    assert not (config.output / "prompts" / "replicate.md").exists()
    assert referenced_output.is_file()
    resumed = PipelineState(config.output)
    assert resumed.get_stage_status("replicate_agent") == "invalidated"
    assert resumed.get_stage_status("report_agents") == "invalidated"


def test_resume_replacement_before_replicate_invalidates_from_codegen(
    tmp_path: Path,
    monkeypatch,
):
    config = _replicate_config(tmp_path)
    state = PipelineState.create(config.output, {"provider": "codex"})
    codebase = config.output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    (codebase / "run.py").write_text("print('preserved')", encoding="utf-8")
    remote_state_path = config.output / "remote_compute" / "instance.json"
    _write_remote_state(remote_state_path)
    for stage_name in ("codegen_agent", "audit_agent", "plan_agent"):
        state.start_stage(stage_name)
        state.complete_stage(stage_name, [stage_name])
    state.resume({"provider": "codex"})
    monkeypatch.setattr(
        "medai.workflow.reconcile_run_computation_instance",
        lambda _config: {
            "replaced": True,
            "instance_uuid": "replacement",
            "status": "running",
        },
    )

    result = prepare_replication_resume(config)

    assert result["rollback"] == "codegen"
    resumed = PipelineState(config.output)
    assert resumed.get_stage_status("codegen_agent") == "invalidated"
    assert resumed.get_stage_checkpoints("codegen_agent") == {
        "source_prepared": True,
        "infrastructure_resume": True,
    }
    assert resumed.get_stage_status("audit_agent") == "invalidated"
    assert resumed.get_stage_status("plan_agent") == "invalidated"
    assert (codebase / "run.py").read_text(encoding="utf-8") == "print('preserved')"


def test_resume_reuses_instance_without_rolling_back_earlier_stage(
    tmp_path: Path,
    monkeypatch,
):
    config = _replicate_config(tmp_path)
    state = PipelineState.create(config.output, {"provider": "codex"})
    _write_remote_state(config.output / "remote_compute" / "instance.json")
    state.start_stage("codegen_agent")
    state.fail("agent interrupted")
    state.resume({"provider": "codex"})
    monkeypatch.setattr(
        "medai.workflow.reconcile_run_computation_instance",
        lambda _config: {
            "replaced": False,
            "instance_uuid": "old-instance",
            "status": "running",
        },
    )

    result = prepare_replication_resume(config)

    assert result["rollback"] is None
    assert PipelineState(config.output).get_stage_status("codegen_agent") == "failed"


def test_resume_completed_report_does_not_reconcile_or_roll_back(
    tmp_path: Path,
    monkeypatch,
):
    config = _replicate_config(tmp_path)
    state = PipelineState.create(config.output, {"provider": "codex"})
    state.start_stage("replicate_agent")
    state.complete_stage("replicate_agent", ["replication"])
    state.start_stage("report_agents")
    state.complete_stage("report_agents", ["report"])
    state.mark_completed()
    state.resume({"provider": "codex"})

    def must_not_reconcile(_config):
        raise AssertionError("completed reports must not touch the instance")

    monkeypatch.setattr(
        "medai.workflow.reconcile_run_computation_instance",
        must_not_reconcile,
    )

    result = prepare_replication_resume(config)

    assert result == {"reconciled": False, "replaced": False, "rollback": None}
    resumed = PipelineState(config.output)
    assert resumed.get_stage_status("replicate_agent") == "completed"
    assert resumed.get_stage_status("report_agents") == "completed"


def test_resume_remote_plan_without_state_fails_before_graph(tmp_path: Path):
    config = _replicate_config(tmp_path)
    state = PipelineState.create(config.output, {"provider": "codex"})
    state.start_stage("codegen_agent")
    state.complete_stage("codegen_agent", ["codegen"])
    missing_state = config.output / "remote_compute" / "instance.json"
    _write_codegen_plan(
        config.output / "codegen" / "codebase" / "codegen_plan.json",
        missing_state,
    )
    state.resume({"provider": "codex"})

    with pytest.raises(RuntimeError, match="Remote computation state is missing"):
        prepare_replication_resume(config)


def test_resume_cloud_replacement_materializes_before_archive(
    tmp_path: Path,
    monkeypatch,
):
    base = _replicate_config(tmp_path)
    config = RunConfig(
        paper=base.paper,
        output=base.output,
        provider=base.provider,
        clouddrive=True,
        drive_provider="aliyun",
        cloud_dataset="mimic-iv",
    )
    state = PipelineState.create(config.output, {"provider": "codex"})
    _write_remote_state(config.output / "remote_compute" / "instance.json")
    (config.output / "replication").mkdir(parents=True)
    (config.output / "report").mkdir(parents=True)
    state.start_stage("replicate_agent")
    state.fail("interrupted")
    state.resume({"provider": "codex"})
    calls = []
    monkeypatch.setattr(
        "medai.workflow.reconcile_run_computation_instance",
        lambda _config: {
            "replaced": True,
            "instance_uuid": "replacement",
            "status": "running",
        },
    )
    monkeypatch.setattr("medai.workflow._cloud_pull", lambda _config: calls.append("pull"))

    prepare_replication_resume(config)

    assert calls == ["pull"]


def test_computation_cleanup_dispatches_provider_and_skips_released_state(
    tmp_path: Path,
    monkeypatch,
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    state_path = output / "remote_compute" / "instance.json"
    state_path.parent.mkdir(parents=True)
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("medai.workflow.subprocess.run", fake_run)
    monkeypatch.setenv("AUTODL_RELEASE_ON_FINISH", "false")

    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": True,
                "provider_state": {"instance_uuid": "instance"},
            }
        ),
        encoding="utf-8",
    )
    release_run_computation_instance(config)
    assert calls == []

    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "instance"},
            }
        ),
        encoding="utf-8",
    )
    release_run_computation_instance(config)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[1].endswith("/computation_provider/scripts/autodl.py")
    assert command[2:] == ["release", "--state", str(state_path)]
    assert kwargs["timeout"] == 120

    calls.clear()
    power_off_run_computation_instance(config)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[2:] == ["power-off", "--state", str(state_path)]
    assert kwargs["timeout"] == 120
