from pathlib import Path

import pytest
from typer.testing import CliRunner

from medai.cli import app
from medai.config import RunConfig
from medai.pipeline_state import PipelineState, build_run_inputs

runner = CliRunner()


def test_help_lists_required_inputs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--paper" in result.stdout
    assert "--output" in result.stdout
    assert "--provider" in result.stdout
    assert "--codex-model" in result.stdout
    assert "--codex-reasoning-effort" in result.stdout
    assert "--smart-replicate" in result.stdout


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
    invoked = []

    class FakeWorkflow:
        def invoke(self, state):
            invoked.append(state["config"].output)

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    result = runner.invoke(
        app,
        [
            "--paper",
            str(paper),
            "--output",
            str(output),
            "--provider",
            "codex",
        ],
    )

    assert result.exit_code == 0
    assert f"Resuming MedAI run: {output}" in result.stdout
    assert invoked == [output]
    assert PipelineState(output).state["resume_count"] == 1


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
