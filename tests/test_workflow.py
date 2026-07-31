import json
from pathlib import Path

import pytest

from medai.artifacts import initialize_manifest
from medai.config import RunConfig
from medai.workflow import codegen_agent_node, create_workflow


def test_full_workflow_with_fake_agents(tmp_path: Path, monkeypatch, capsys):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("source", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=repo,
        data=None,
        siliconflow_config=None,
    )
    initialize_manifest(output, {"paper": str(paper), "provider": "codex"})
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
                                "kind": "numeric",
                                "paper_result": 0.9,
                                "provenance": {"page": 1, "section": "Results"},
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
                                "claims": ["C1"],
                                "artifacts": ["Figure 1"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif name == "codegen.md":
            (output / "codegen" / "codebase" / "data_inventory.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset": {
                            "id": None,
                            "root": None,
                            "adapter": None,
                            "status": "not_supplied",
                        },
                        "scan": {
                            "files_scanned": 0,
                            "bytes_scanned": 0,
                            "truncated": False,
                            "limits": {},
                        },
                        "catalog": [],
                        "explored_files": [],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            (output / "codegen" / "codebase" / "codegen_plan.json").write_text(
                json.dumps(
                    {
                        "files": [{"path": "run.py", "responsibility": "Run experiment"}],
                        "dependency_order": ["run.py"],
                        "entry_points": ["run.py"],
                        "shared_state": "Files",
                        "ambiguities": [],
                    }
                ),
                encoding="utf-8",
            )
        elif name == "audit.md":
            (output / "audit" / "replicate_plan.json").write_text(
                json.dumps(
                    {
                        "experiments": [
                            {
                                "experiment_id": "E1",
                                "claims": ["C1"],
                                "artifacts": ["Figure 1"],
                                "steps": [
                                    {
                                        "step_id": "S1",
                                        "description": "Run",
                                        "command": "python run.py",
                                        "expected_outputs": ["figure.png"],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        elif name == "replicate.md":
            result_dir = output / "replication" / "E1"
            result_dir.mkdir(parents=True)
            (result_dir / "figure.png").write_bytes(b"png")
            (result_dir / "result.json").write_text(
                json.dumps(
                    {
                        "experiment_id": "E1",
                        "claims": [
                            {
                                "claim_id": "C1",
                                "reproduced_result": 0.89,
                                "evidence": ["replication/E1/result.json"],
                            }
                        ],
                        "artifacts": [
                            {
                                "artifact_id": "Figure 1",
                                "path": "replication/E1/figure.png",
                            }
                        ],
                        "commands": ["python run.py"],
                    }
                ),
                encoding="utf-8",
            )
        elif name == "report_E1.md":
            (output / "report" / "reproduction_report.md").write_text(
                "# Report\n\n## E1\nCompared C1 and Figure 1.\n",
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
        "enter codegen audit stage",
        "enter replicate stage",
        "enter report stage",
    ]
    assert Path(result["report_path"]).is_file()
    assert transcript_paths == [
        "preprocessing/preprocessing_transcript.jsonl",
        "codegen/codegen_transcript.jsonl",
        "audit/audit_transcript.jsonl",
        "replication/replication_transcript.jsonl",
        "report/E1_transcript.jsonl",
    ]
    assert (output / "codegen" / "codebase" / "README.md").is_file()
    assert (output / "codegen" / "codebase" / "data_inventory.json").is_file()
    dataset_patch_path = output / "system_maintenance" / "dataset" / "patch.json"
    assert json.loads(dataset_patch_path.read_text(encoding="utf-8")) == []
    codegen_prompt = (output / "prompts" / "codegen.md").read_text(encoding="utf-8")
    assert str(dataset_patch_path) in codegen_prompt
    assert '"file name": "dataset_graph.yaml"' in codegen_prompt
    assert "/explore-data/SKILL.md" in codegen_prompt
    assert "explore-data-analysis" not in codegen_prompt
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert list(manifest["stages"]) == [
        "preflight",
        "preprocess_pdf",
        "preprocessing_agent",
        "codegen_agent",
        "audit_agent",
        "replicate_agent",
        "report_agents",
    ]


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
    monkeypatch.setattr(workflow, "replicate_agent_node", must_not_run)
    monkeypatch.setattr(workflow, "report_agents_node", must_not_run)

    with pytest.raises(RuntimeError, match="stop"):
        workflow.create_workflow().invoke({"config": object()})
    assert calls == ["preflight", "preprocess_pdf"]


def test_codegen_requires_data_inventory(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    output.mkdir()
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    initialize_manifest(output, {"paper": str(paper), "provider": "codex"})
    resources_path = tmp_path / "resources.json"
    resources_path.write_text(
        json.dumps({"cpu": {}, "memory": {}, "disk": {}, "gpus": []}),
        encoding="utf-8",
    )

    def fake_agent(*, working_dir, **kwargs):
        (working_dir / "codegen_plan.json").write_text(
            json.dumps(
                {
                    "files": [{"path": "run.py", "responsibility": "Run"}],
                    "dependency_order": ["run.py"],
                    "entry_points": ["run.py"],
                    "shared_state": "Files",
                    "ambiguities": [],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    with pytest.raises(RuntimeError, match="Required artifact is missing"):
        codegen_agent_node(
            {
                "config": config,
                "paper_markdown": str(tmp_path / "paper.md"),
                "claims_path": str(tmp_path / "claims.json"),
                "experiments_path": str(tmp_path / "experiments.json"),
                "resources_path": str(resources_path),
            }
        )


def test_codegen_rejects_inventory_that_disagrees_with_data_input(
    tmp_path: Path,
    monkeypatch,
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "raw"
    data.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=data,
        siliconflow_config=None,
    )
    initialize_manifest(output, {"paper": str(paper), "provider": "codex"})
    resources_path = tmp_path / "resources.json"
    resources_path.write_text(
        json.dumps({"cpu": {}, "memory": {}, "disk": {}, "gpus": []}),
        encoding="utf-8",
    )

    def fake_agent(*, working_dir, **kwargs):
        (working_dir / "data_inventory.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "dataset": {
                        "id": None,
                        "root": None,
                        "adapter": None,
                        "status": "not_supplied",
                    },
                    "scan": {
                        "files_scanned": 0,
                        "bytes_scanned": 0,
                        "truncated": False,
                        "limits": {},
                    },
                    "catalog": [],
                    "explored_files": [],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        (working_dir / "codegen_plan.json").write_text(
            json.dumps(
                {
                    "files": [{"path": "run.py", "responsibility": "Run"}],
                    "dependency_order": ["run.py"],
                    "entry_points": ["run.py"],
                    "shared_state": "Files",
                    "ambiguities": [],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    with pytest.raises(ValueError, match="must report explored"):
        codegen_agent_node(
            {
                "config": config,
                "paper_markdown": str(tmp_path / "paper.md"),
                "claims_path": str(tmp_path / "claims.json"),
                "experiments_path": str(tmp_path / "experiments.json"),
                "resources_path": str(resources_path),
            }
        )
