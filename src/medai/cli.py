from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import typer

from medai.autoresearch import create_autoresearch_workflow
from medai.config import AutoResearchConfig, RunConfig
from medai.pipeline_state import (
    PipelineState,
    build_autoresearch_inputs,
    build_run_inputs,
)
from medai.workflow import (
    PartialDataAwaitingConfirmation,
    PartialDataStopped,
    create_workflow,
    power_off_run_computation_instance,
    prepare_autoresearch_resume,
    prepare_replication_resume,
    release_run_computation_instance,
)

app = typer.Typer(
    name="medai",
    help="Run MedAI replication or Auto Research workflows.",
    no_args_is_help=True,
)


def _new_autoresearch_output(replicate_run: Path) -> Path:
    root = replicate_run / "autoresearch"
    root.mkdir(parents=True, exist_ok=True)
    indices = [
        int(match.group(1))
        for path in root.iterdir()
        if path.is_dir() and (match := re.fullmatch(r"campaign_(\d+)", path.name))
    ]
    index = max(indices, default=0) + 1
    while True:
        output = root / f"campaign_{index:03d}"
        try:
            output.mkdir()
            return output
        except FileExistsError:
            index += 1


@app.callback(invoke_without_command=True)
def run(
    replicate: bool = typer.Option(False, "--replicate", help="Run paper replication"),
    autoresearch: bool = typer.Option(
        False,
        "--autoresearch",
        help="Run Auto Research from a completed replication",
    ),
    paper: Optional[Path] = typer.Option(None, "--paper", help="Path to paper.pdf"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Replication output or explicit Auto Research campaign output",
    ),
    replicate_run: Optional[Path] = typer.Option(
        None,
        "--replicate-run",
        help="Completed replication run used as the Auto Research base",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Provider (replicate default: codex; Auto Research default: inherit)",
    ),
    repo: Optional[Path] = typer.Option(None, "--repo", help="Optional code repository"),
    data: Optional[list[str]] = typer.Option(
        None,
        "--data",
        help="Repeat for each local data directory or cloud dataset name",
    ),
    dataset_name: Optional[list[str]] = typer.Option(
        None,
        "--dataset-name",
        hidden=True,
    ),
    clouddrive: bool = typer.Option(
        False,
        "--clouddrive",
        help="Make the configured provider cloud dataset available for remote execution",
    ),
    cloud_dataset: Optional[list[str]] = typer.Option(
        None,
        "--cloud-dataset",
        hidden=True,
    ),
    siliconflow_config: Optional[Path] = typer.Option(
        None,
        "--siliconflow-config",
        help="Dotenv file for codex-siliconflow",
    ),
    codex_model: Optional[str] = typer.Option(
        None,
        "--codex-model",
        help="Codex model (default: MEDAI_CODEX_MODEL)",
    ),
    codex_reasoning_effort: Optional[str] = typer.Option(
        None,
        "--codex-reasoning-effort",
        help="Codex reasoning effort (default: MEDAI_CODEX_REASONING_EFFORT)",
    ),
    smart_replicate: bool = typer.Option(
        False,
        "--smart-replicate",
        help="Allow up to five audited anchor-guided replication adjustments",
    ),
    on_partial_data: str = typer.Option(
        "ask",
        "--on-partial-data",
        help="Partial-data policy for replication: ask, continue, or stop",
    ),
    max_iter: Optional[int] = typer.Option(
        None,
        "--max-iter",
        help="Auto Research idea-generation rounds (default: 1, maximum: 10)",
    ),
    assessment_threshold: Optional[float] = typer.Option(
        None,
        "--assessment-threshold",
        help="Minimum weighted idea-assessment score on the -5 to 5 scale (default: 0.0)",
    ),
) -> None:
    try:
        if replicate == autoresearch:
            raise ValueError("Exactly one of --replicate or --autoresearch is required")

        if replicate:
            if paper is None:
                raise ValueError("--replicate requires --paper")
            if output is None:
                raise ValueError("--replicate requires --output")
            if (
                max_iter is not None
                or assessment_threshold is not None
                or replicate_run is not None
            ):
                raise ValueError(
                    "--max-iter, --assessment-threshold, and --replicate-run require "
                    "--autoresearch"
                )
            config: RunConfig | AutoResearchConfig = RunConfig.create(
                paper=paper,
                output=output,
                provider=provider or "codex",
                repo=repo,
                data=data,
                datasets=dataset_name,
                siliconflow_config=siliconflow_config,
                codex_model=codex_model,
                codex_reasoning_effort=codex_reasoning_effort,
                smart_replicate=smart_replicate,
                clouddrive=clouddrive,
                cloud_dataset=cloud_dataset,
                on_partial_data=on_partial_data,
            )
            inputs = build_run_inputs(config)
            workflow = create_workflow()
            completion_label = "Replication"
        else:
            if (
                paper is not None
                or repo is not None
                or data is not None
                or dataset_name is not None
                or smart_replicate
                or clouddrive
                or cloud_dataset is not None
                or on_partial_data != "ask"
            ):
                raise ValueError(
                    "--autoresearch does not accept --paper, --repo, --data, --dataset-name, "
                    "--clouddrive, --cloud-dataset, or --smart-replicate"
                )
            if replicate_run is None:
                raise ValueError("--autoresearch requires --replicate-run")
            resolved_base_run = replicate_run.expanduser().resolve()
            resolved_output = (
                output.expanduser().resolve()
                if output is not None
                else _new_autoresearch_output(resolved_base_run)
            )
            config = AutoResearchConfig.create(
                base_run=resolved_base_run,
                output=resolved_output,
                provider=provider,
                max_iter=1 if max_iter is None else max_iter,
                assessment_threshold=(
                    0.0 if assessment_threshold is None else assessment_threshold
                ),
                siliconflow_config=siliconflow_config,
                codex_model=codex_model,
                codex_reasoning_effort=codex_reasoning_effort,
            )
            inputs = build_autoresearch_inputs(config)
            workflow = create_autoresearch_workflow()
            completion_label = "Auto Research"

        skip_release_retry = False
        if (config.output / "manifest.json").exists():
            pipeline_state = PipelineState(config.output)
            previous_manifest_status = pipeline_state.state.get("status")
            cleanup_stage = "report_agents" if replicate else "final_report"
            skip_release_retry = bool(
                pipeline_state.is_stage_completed(cleanup_stage)
                and pipeline_state.state.get("cleanup_warning")
            )
            pipeline_state.resume(inputs)
            typer.echo(f"Resuming {completion_label} run: {config.output}")
        else:
            if config.output.is_dir() and any(config.output.iterdir()):
                raise ValueError(
                    f"Output is not empty and has no MedAI pipeline state: {config.output}"
                )
            pipeline_state = PipelineState.create(config.output, inputs)
        run_active = True
        if replicate and pipeline_state.state.get("resume_count", 0) > 0:
            if not (
                previous_manifest_status == "awaiting_confirmation"
                and config.on_partial_data == "stop"
            ):
                prepare_replication_resume(config)
        elif autoresearch and pipeline_state.state.get("resume_count", 0) > 0:
            prepare_autoresearch_resume(config)
        result = workflow.invoke({"config": config})
        if not skip_release_retry:
            try:
                release_run_computation_instance(config)
            except Exception as cleanup_exc:
                PipelineState(config.output).record_cleanup_warning(
                    "release",
                    str(cleanup_exc),
                )
                typer.echo(
                    f"WARNING: {completion_label.casefold()} completed but release failed: {cleanup_exc}",
                    err=True,
                )
    except PartialDataAwaitingConfirmation as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=3) from exc
    except PartialDataStopped as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=4) from exc
    except Exception as exc:
        if "run_active" in locals() and (config.output / "manifest.json").is_file():
            cleanup_error = None
            try:
                power_off_run_computation_instance(config)
            except Exception as cleanup_exc:
                cleanup_error = str(cleanup_exc)
            message = str(exc)
            if cleanup_error:
                message = f"{message}; cleanup error: {cleanup_error}"
            PipelineState(config.output).fail(message)
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if autoresearch:
        final_state = PipelineState(config.output).state
        if final_state["status"] == "ineligible":
            typer.echo(
                "Auto Research ineligible: "
                f"{final_state.get('ineligible_reason', 'not a supervised prediction task')}"
            )
        else:
            typer.echo(f"Auto Research complete: {result['report_path']}")
    else:
        typer.echo(f"Replication complete: {result['report_path']}")


if __name__ == "__main__":
    app()
