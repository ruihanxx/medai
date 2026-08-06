import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from medai.cli import app
from medai.config import AutoResearchConfig, RunConfig
from medai.pipeline_state import PipelineState, build_run_inputs

runner = CliRunner()


def test_help_lists_required_inputs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--replicate" in result.stdout
    assert "--autoresearch" in result.stdout
    assert "--paper" in result.stdout
    assert "--output" in result.stdout
    assert "--provider" in result.stdout
    assert "--data" in result.stdout
    assert "--clouddrive" in result.stdout
    assert "--codex-model" in result.stdout
    assert "--codex-reasoning-effort" in result.stdout
    assert "--smart-replicate" in result.stdout
    assert "--max-iter" in result.stdout
    assert "--assessment-threshold" in result.stdout


def test_cli_requires_exactly_one_mode(tmp_path: Path):
    result = runner.invoke(app, ["--output", str(tmp_path / "output")])
    assert result.exit_code == 1
    assert "Exactly one" in result.stderr

    result = runner.invoke(
        app,
        [
            "--replicate",
            "--autoresearch",
            "--output",
            str(tmp_path / "output"),
        ],
    )
    assert result.exit_code == 1
    assert "Exactly one" in result.stderr


def test_codex_settings_are_loaded_from_environment(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("MEDAI_CODEX_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("MEDAI_CODEX_REASONING_EFFORT", "HIGH")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )

    assert config.codex_model == "gpt-5.6-terra"
    assert config.codex_reasoning_effort == "high"
    assert config.smart_replicate is False


def test_codex_reasoning_effort_is_validated(tmp_path: Path):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="Unsupported Codex reasoning effort"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data=None,
            siliconflow_config=None,
            codex_reasoning_effort="extreme",
        )


def test_cloud_drive_config_and_manifest_are_remote_only(
    tmp_path: Path, monkeypatch
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("AUTODL_TOKEN", "api-secret")
    monkeypatch.setenv("AUTODL_IMAGE_UUID", "image-id")
    monkeypatch.setenv("AUTODL_AUTOPANEL_PASSWORD", "panel-secret")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data="mimic-iv",
        siliconflow_config=None,
        clouddrive=True,
    )
    inputs = build_run_inputs(config)

    assert config.data is None
    assert config.cloud_dataset == "mimic-iv"
    assert config.drive_provider == "aliyun"
    assert inputs["data"] is None
    assert inputs["data_source"] is None
    assert inputs["clouddrive"] is True
    assert inputs["cloud_source"] == "medai/mimic-iv"
    assert "panel-secret" not in json.dumps(inputs)


@pytest.mark.parametrize("dataset", ["../mimic", "a/b", ".", "/absolute"])
def test_cloud_drive_rejects_unsafe_dataset_names(
    tmp_path: Path, monkeypatch, dataset: str
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("AUTODL_TOKEN", "token")
    monkeypatch.setenv("AUTODL_IMAGE_UUID", "image")
    monkeypatch.setenv("AUTODL_AUTOPANEL_PASSWORD", "password")

    with pytest.raises(ValueError, match="safe directory name"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data=dataset,
            siliconflow_config=None,
            clouddrive=True,
        )


def test_cloud_drive_requires_supported_provider_and_password(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("AUTODL_TOKEN", "token")
    monkeypatch.setenv("AUTODL_IMAGE_UUID", "image")
    monkeypatch.setenv("MEDAI_DRIVE_PROVIDER", "other")

    with pytest.raises(ValueError, match="does not support drive"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data="mimic-iv",
            siliconflow_config=None,
            clouddrive=True,
        )

    monkeypatch.setenv("MEDAI_DRIVE_PROVIDER", "aliyun")
    with pytest.raises(ValueError, match="AUTODL_AUTOPANEL_PASSWORD"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data="mimic-iv",
            siliconflow_config=None,
            clouddrive=True,
        )


def test_config_requires_pdf(tmp_path: Path):
    paper = tmp_path / "paper.txt"
    paper.write_text("not pdf", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a PDF"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data=None,
            siliconflow_config=None,
        )


def test_siliconflow_config_is_provider_specific(tmp_path: Path):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    provider_config = tmp_path / "provider.env"
    provider_config.write_text("SILICONFLOW_API_KEY=test\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires --provider"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data=None,
            siliconflow_config=provider_config,
        )


def test_output_cannot_be_inside_repo(tmp_path: Path):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="cannot be inside"):
        RunConfig.create(
            paper=paper,
            output=repo / "run",
            provider="codex",
            repo=repo,
            data=None,
            siliconflow_config=None,
        )


def test_existing_output_resumes_matching_run(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    PipelineState.create(output, build_run_inputs(config))
    events = []

    class FakeWorkflow:
        def invoke(self, state):
            events.append(("invoke", state["config"].output))
            return {"report_path": str(output / "report.md")}

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        "medai.cli.prepare_replication_resume",
        lambda config: events.append(("prepare", config.output)),
    )
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    result = runner.invoke(
        app,
        [
            "--replicate",
            "--paper",
            str(paper),
            "--output",
            str(output),
            "--provider",
            "codex",
        ],
    )

    assert result.exit_code == 0
    assert f"Resuming Replication run: {output}" in result.stdout
    assert events == [("prepare", output), ("invoke", output)]
    assert PipelineState(output).state["resume_count"] == 1


def test_replicate_without_data_fails_in_preflight(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    result = runner.invoke(
        app,
        [
            "--replicate",
            "--paper",
            str(paper),
            "--output",
            str(output),
            "--provider",
            "codex",
        ],
    )

    assert result.exit_code == 1
    assert "require --data" in result.stderr
    manifest = PipelineState(output).state
    assert manifest["status"] == "failed"
    assert manifest["stages"]["preflight"]["status"] == "failed"
    assert list(manifest["stages"]) == ["preflight"]


def test_failure_preserves_stage_updates_written_by_workflow(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    PipelineState.create(output, build_run_inputs(config))

    class FakeWorkflow:
        def invoke(self, state):
            pipeline_state = PipelineState(state["config"].output)
            pipeline_state.start_stage("plan_agent")
            raise RuntimeError("plan failed")

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    result = runner.invoke(
        app,
        [
            "--replicate",
            "--paper",
            str(paper),
            "--output",
            str(output),
            "--provider",
            "codex",
        ],
    )

    assert result.exit_code == 1
    manifest = PipelineState(output).state
    assert manifest["stages"]["plan_agent"]["status"] == "failed"
    assert manifest["stages"]["plan_agent"]["error"] == "plan failed"


def test_replicate_failure_powers_off_without_releasing(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    cleanup_calls = []

    class FakeWorkflow:
        def invoke(self, state):
            raise RuntimeError("replicate failed")

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        "medai.cli.power_off_run_computation_instance",
        lambda config: cleanup_calls.append(("power-off", config.output)),
    )
    monkeypatch.setattr(
        "medai.cli.release_run_computation_instance",
        lambda config: cleanup_calls.append(("release", config.output)),
    )

    result = runner.invoke(
        app,
        [
            "--replicate",
            "--paper",
            str(paper),
            "--output",
            str(output),
            "--provider",
            "codex",
        ],
    )

    assert result.exit_code == 1
    assert cleanup_calls == [("power-off", output)]


def test_release_failure_keeps_completed_run_and_is_not_retried(
    tmp_path: Path,
    monkeypatch,
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    release_calls = []

    class FakeWorkflow:
        def invoke(self, state):
            pipeline_state = PipelineState(state["config"].output)
            if not pipeline_state.is_stage_completed("report_agents"):
                pipeline_state.start_stage("report_agents")
                pipeline_state.complete_stage("report_agents", ["report"])
            pipeline_state.mark_completed()
            return {"report_path": str(output / "report" / "reproduction_report.md")}

    def fail_release(config):
        release_calls.append(config.output)
        raise RuntimeError("provider cleanup unavailable")

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr("medai.cli.release_run_computation_instance", fail_release)

    arguments = [
        "--replicate",
        "--paper",
        str(paper),
        "--output",
        str(output),
        "--provider",
        "codex",
    ]
    first = runner.invoke(app, arguments)

    assert first.exit_code == 0, first.stderr
    assert "replication completed but release failed" in first.stderr
    after_first = PipelineState(output).state
    assert after_first["status"] == "completed"
    assert after_first["cleanup_warning"]["operation"] == "release"
    assert "provider cleanup unavailable" in after_first["cleanup_warning"]["error"]

    second = runner.invoke(app, arguments)

    assert second.exit_code == 0, second.stderr
    assert release_calls == [output]
    assert PipelineState(output).state["status"] == "completed"


def test_autoresearch_cli_uses_base_output_and_inherited_provider(
    tmp_path: Path,
    monkeypatch,
):
    base_run = tmp_path / "base"
    base_run.mkdir()
    (base_run / "manifest.json").write_text(
        json.dumps({"inputs": {"provider": "codex"}}),
        encoding="utf-8",
    )
    invoked = []

    class FakeWorkflow:
        def invoke(self, state):
            invoked.append(state["config"])
            PipelineState(state["config"].output).mark_completed()
            report_path = state["config"].output / "report" / "auto_research_report.md"
            return {"report_path": str(report_path)}

    monkeypatch.setattr(
        "medai.cli.build_autoresearch_inputs",
        lambda config: {"workflow": "autoresearch", "provider": config.provider},
    )
    monkeypatch.setattr(
        "medai.cli.create_autoresearch_workflow",
        lambda: FakeWorkflow(),
    )
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    result = runner.invoke(
        app,
        ["--autoresearch", "--output", str(base_run)],
    )

    assert result.exit_code == 0, result.stdout
    assert len(invoked) == 1
    assert invoked[0].base_run == base_run
    assert invoked[0].output == base_run / "autoresearch"
    assert invoked[0].provider == "codex"
    assert invoked[0].max_iter == 1
    assert invoked[0].assessment_threshold == 0.0


def test_autoresearch_config_inherits_base_provider_and_data(tmp_path: Path):
    base_run = tmp_path / "base"
    base_run.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (base_run / "manifest.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "provider": "codex",
                    "codex_model": "gpt-test",
                    "codex_reasoning_effort": "high",
                    "data": str(data),
                }
            }
        ),
        encoding="utf-8",
    )

    config = AutoResearchConfig.create(
        base_run=base_run,
        output=base_run / "autoresearch",
        provider=None,
        max_iter=1,
        siliconflow_config=None,
    )

    assert config.provider == "codex"
    assert config.codex_model == "gpt-test"
    assert config.codex_reasoning_effort == "high"
    assert config.data == data
    assert config.assessment_threshold == 0.0

    override = AutoResearchConfig.create(
        base_run=base_run,
        output=base_run / "autoresearch",
        provider="claude",
        max_iter=1,
        siliconflow_config=None,
    )
    assert override.provider == "claude"
    assert override.codex_model is None
    assert override.codex_reasoning_effort is None

    with pytest.raises(ValueError, match="between 1 and 10"):
        AutoResearchConfig.create(
            base_run=base_run,
            output=base_run / "autoresearch",
            provider=None,
            max_iter=11,
            siliconflow_config=None,
        )

    with pytest.raises(ValueError, match="finite non-negative"):
        AutoResearchConfig.create(
            base_run=base_run,
            output=base_run / "autoresearch",
            provider=None,
            assessment_threshold=-0.1,
            siliconflow_config=None,
        )

    result = runner.invoke(
        app,
        [
            "--autoresearch",
            "--output",
            str(base_run),
            "--max-iter",
            "0",
        ],
    )
    assert result.exit_code == 1
    assert "between 1 and 10" in result.stderr


def test_autoresearch_rejects_cloud_backed_base_run(tmp_path: Path):
    base_run = tmp_path / "base"
    base_run.mkdir()
    (base_run / "manifest.json").write_text(
        json.dumps({"inputs": {"provider": "codex", "clouddrive": True}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cloud-backed"):
        AutoResearchConfig.create(
            base_run=base_run,
            output=base_run / "autoresearch",
            provider=None,
            siliconflow_config=None,
        )
