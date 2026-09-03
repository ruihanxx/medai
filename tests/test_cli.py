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
    assert "completed local replication" not in result.stdout
    assert "--paper" in result.stdout
    assert "--output" in result.stdout
    assert "--replicate-run" in result.stdout
    assert "--provider" in result.stdout
    assert "--data" in result.stdout
    assert "--clouddrive" in result.stdout
    assert "--force-remote" in result.stdout
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
    assert config.on_partial_data == "continue"


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
    monkeypatch.setenv("VAST_API_KEY", "api-secret")
    monkeypatch.setenv("VASTAI_IMAGE", "image-id")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "connection-id")

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
    assert config.drive_provider == "google-drive"
    assert inputs["data"] is None
    assert inputs["data_source"] is None
    assert inputs["clouddrive"] is True
    assert inputs["cloud_source"] == "medai/mimic-iv"
    assert "api-secret" not in json.dumps(inputs)


def test_local_and_cloud_data_are_recorded_together(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "mimic-iv"
    data.mkdir()
    monkeypatch.setenv("VAST_API_KEY", "api-secret")
    monkeypatch.setenv("VASTAI_IMAGE", "image-id")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "connection-id")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data=data,
        siliconflow_config=None,
        clouddrive=True,
        cloud_dataset="mimic-iv",
    )
    inputs = build_run_inputs(config)

    assert config.data == data.resolve()
    assert config.cloud_dataset == "mimic-iv"
    assert inputs["data"] == str(data.resolve())
    assert inputs["clouddrive"] is True
    assert inputs["cloud_source"] == "medai/mimic-iv"


def test_multiple_local_and_cloud_datasets_are_preserved(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    dataset_root = tmp_path / "datasets"
    datasets = [dataset_root / "mimic-iv", dataset_root / "eicu"]
    for dataset in datasets:
        dataset.mkdir(parents=True)
    monkeypatch.setenv("VAST_API_KEY", "api-secret")
    monkeypatch.setenv("VASTAI_IMAGE", "image-id")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "connection-id")
    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data=datasets,
        siliconflow_config=None,
        clouddrive=True,
        cloud_dataset=["mimic-iv", "eicu"],
    )
    inputs = build_run_inputs(config)

    assert config.data == dataset_root.resolve()
    assert config.dataset_names == ("mimic-iv", "eicu")
    assert config.selected_cloud_datasets == ("mimic-iv", "eicu")
    assert inputs["datasets"] == ["mimic-iv", "eicu"]
    assert inputs["data_sources"] == [str(dataset) for dataset in datasets]
    assert inputs["data_source"] is None
    assert inputs["cloud_datasets"] == ["mimic-iv", "eicu"]
    assert inputs["cloud_sources"] == ["medai/mimic-iv", "medai/eicu"]


@pytest.mark.parametrize("dataset", ["../mimic", "a/b", ".", "/absolute"])
def test_cloud_drive_rejects_unsafe_dataset_names(
    tmp_path: Path, monkeypatch, dataset: str
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("VAST_API_KEY", "token")
    monkeypatch.setenv("VASTAI_IMAGE", "image")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "connection-id")

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


def test_cloud_drive_requires_supported_provider_and_connection(
    tmp_path: Path, monkeypatch
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    monkeypatch.setenv("VAST_API_KEY", "token")
    monkeypatch.setenv("VASTAI_IMAGE", "image")
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

    monkeypatch.setenv("MEDAI_DRIVE_PROVIDER", "google-drive")
    with pytest.raises(ValueError, match="VASTAI_GOOGLE_DRIVE_CONNECTION_ID"):
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


def test_resume_rejects_new_siliconflow_reasoning_effort(tmp_path: Path):
    pipeline = PipelineState.create(
        tmp_path / "output", {"provider": "codex-siliconflow"}
    )
    with pytest.raises(RuntimeError, match="siliconflow_reasoning_effort"):
        pipeline.resume(
            {
                "provider": "codex-siliconflow",
                "siliconflow_reasoning_effort": "max",
            }
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


def test_replicate_without_data_reaches_paper_preprocessing(tmp_path: Path, monkeypatch):
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
    assert "Host MinerU output is not configured" in result.stderr
    manifest = PipelineState(output).state
    assert manifest["status"] == "failed"
    assert manifest["stages"]["preprocess_pdf"]["status"] == "failed"
    assert "preflight" not in manifest["stages"]


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


def test_replicate_failure_powers_off_and_releases(tmp_path: Path, monkeypatch):
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
    assert cleanup_calls == [("power-off", output), ("release", output)]


def test_replicate_failure_preserves_primary_error_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    output = tmp_path / "output"
    cleanup_calls = []

    class FakeWorkflow:
        def invoke(self, _state):
            raise RuntimeError("cloud-monitor failed")

    def fail_cleanup(operation, error):
        def cleanup(config):
            cleanup_calls.append((operation, config.output))
            raise RuntimeError(error)

        return cleanup

    monkeypatch.setattr("medai.cli.create_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        "medai.cli.power_off_run_computation_instance",
        fail_cleanup("power-off", "stop unavailable"),
    )
    monkeypatch.setattr(
        "medai.cli.release_run_computation_instance",
        fail_cleanup("release", "destroy unavailable"),
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
    assert cleanup_calls == [("power-off", output), ("release", output)]
    assert "ERROR: cloud-monitor failed; cleanup error:" in result.stderr
    assert "power-off: stop unavailable" in result.stderr
    assert "release: destroy unavailable" in result.stderr
    assert PipelineState(output).state["error"].startswith("cloud-monitor failed;")


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


def test_autoresearch_cli_allocates_and_resumes_campaign_output(
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
    monkeypatch.setattr("medai.cli.prepare_autoresearch_resume", lambda config: None)
    monkeypatch.setattr("medai.cli.release_run_computation_instance", lambda config: None)

    first = runner.invoke(
        app,
        ["--autoresearch", "--replicate-run", str(base_run)],
    )

    campaign_001 = base_run / "autoresearch" / "campaign_001"
    assert first.exit_code == 0, first.stdout
    assert invoked[0].base_run == base_run
    assert invoked[0].output == campaign_001
    assert invoked[0].provider == "codex"
    assert invoked[0].max_iter == 1
    assert invoked[0].assessment_threshold == 0.0

    resumed = runner.invoke(
        app,
        [
            "--autoresearch",
            "--replicate-run",
            str(base_run),
            "--output",
            str(campaign_001),
        ],
    )
    assert resumed.exit_code == 0, resumed.stdout
    assert f"Resuming Auto Research run: {campaign_001}" in resumed.stdout
    assert invoked[1].output == campaign_001
    assert PipelineState(campaign_001).state["resume_count"] == 1

    second_campaign = runner.invoke(
        app,
        ["--autoresearch", "--replicate-run", str(base_run)],
    )
    assert second_campaign.exit_code == 0, second_campaign.stdout
    assert invoked[2].output == base_run / "autoresearch" / "campaign_002"


def test_autoresearch_failure_powers_off_and_releases(tmp_path: Path, monkeypatch):
    base_run = tmp_path / "base"
    base_run.mkdir()
    (base_run / "manifest.json").write_text(
        json.dumps({"inputs": {"provider": "codex"}}),
        encoding="utf-8",
    )
    cleanup_calls = []

    class FakeWorkflow:
        def invoke(self, _state):
            raise RuntimeError("autoresearch failed")

    monkeypatch.setattr(
        "medai.cli.build_autoresearch_inputs",
        lambda config: {"workflow": "autoresearch", "provider": config.provider},
    )
    monkeypatch.setattr("medai.cli.create_autoresearch_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        "medai.cli.power_off_run_computation_instance",
        lambda config: cleanup_calls.append(("power-off", config.output)),
    )
    monkeypatch.setattr(
        "medai.cli.release_run_computation_instance",
        lambda config: cleanup_calls.append(("release", config.output)),
    )

    campaign = base_run / "autoresearch" / "campaign_001"
    result = runner.invoke(
        app,
        [
            "--autoresearch",
            "--replicate-run",
            str(base_run),
            "--output",
            str(campaign),
        ],
    )

    assert result.exit_code == 1
    assert cleanup_calls == [("power-off", campaign), ("release", campaign)]


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
            "--replicate-run",
            str(base_run),
            "--max-iter",
            "0",
        ],
    )
    assert result.exit_code == 1
    assert "between 1 and 10" in result.stderr


def test_autoresearch_inherits_vast_google_drive_base_run(tmp_path: Path, monkeypatch):
    base_run = tmp_path / "base"
    base_run.mkdir()
    monkeypatch.setenv("VAST_API_KEY", "test-key")
    monkeypatch.setenv("VASTAI_IMAGE", "test-image")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "drive-1")
    (base_run / "manifest.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "provider": "codex",
                    "clouddrive": True,
                    "computation_provider": "vastai",
                    "drive_provider": "google-drive",
                    "cloud_dataset": "mimic-iv",
                    "cloud_source": "medai/mimic-iv",
                }
            }
        ),
        encoding="utf-8",
    )

    config = AutoResearchConfig.create(
        base_run=base_run,
        output=base_run / "autoresearch",
        provider=None,
        siliconflow_config=None,
    )

    assert config.clouddrive is True
    assert config.data is None
    assert config.computation_provider == "vastai"
    assert config.drive_provider == "google-drive"
    assert config.cloud_dataset == "mimic-iv"
    assert config.cloud_source == "medai/mimic-iv"
