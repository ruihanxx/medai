from __future__ import annotations

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
from medai.workflow import create_workflow, release_run_computation_instance

app = typer.Typer(
    name="medai",
    help="Run MedAI replication or Auto Research workflows.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def run(
    replicate: bool = typer.Option(False, "--replicate", help="Run paper replication"),
    autoresearch: bool = typer.Option(
        False,
        "--autoresearch",
        help="Run Auto Research from a completed local replication",
    ),
    paper: Optional[Path] = typer.Option(None, "--paper", help="Path to paper.pdf"),
    output: Path = typer.Option(
        ...,
        "--output",
        help="Replication output, or completed base run for Auto Research",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Provider (replicate default: codex; Auto Research default: inherit)",
    ),
    repo: Optional[Path] = typer.Option(None, "--repo", help="Optional code repository"),
    data: Optional[Path] = typer.Option(None, "--data", help="Optional local data directory"),
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
    max_iter: Optional[int] = typer.Option(
        None,
        "--max-iter",
        help="Auto Research idea-generation rounds (default: 1, maximum: 10)",
    ),
    base_run: Optional[Path] = typer.Option(None, "--base-run", hidden=True),
) -> None:
    try:
        if replicate == autoresearch:
            raise ValueError("Exactly one of --replicate or --autoresearch is required")

        if replicate:
            if paper is None:
                raise ValueError("--replicate requires --paper")
            if max_iter is not None or base_run is not None:
                raise ValueError("--max-iter and --base-run require --autoresearch")
            config: RunConfig | AutoResearchConfig = RunConfig.create(
                paper=paper,
                output=output,
                provider=provider or "codex",
                repo=repo,
                data=data,
                siliconflow_config=siliconflow_config,
                codex_model=codex_model,
                codex_reasoning_effort=codex_reasoning_effort,
                smart_replicate=smart_replicate,
            )
            inputs = build_run_inputs(config)
            workflow = create_workflow()
            completion_label = "Replication"
        else:
            if paper is not None or repo is not None or data is not None or smart_replicate:
                raise ValueError(
                    "--autoresearch does not accept --paper, --repo, --data, "
                    "or --smart-replicate"
                )
            resolved_base_run = base_run or output
            resolved_output = output if base_run else output / "autoresearch"
            config = AutoResearchConfig.create(
                base_run=resolved_base_run,
                output=resolved_output,
                provider=provider,
                max_iter=max_iter or 1,
                siliconflow_config=siliconflow_config,
                codex_model=codex_model,
                codex_reasoning_effort=codex_reasoning_effort,
            )
            inputs = build_autoresearch_inputs(config)
            workflow = create_autoresearch_workflow()
            completion_label = "Auto Research"

        if (config.output / "manifest.json").exists():
            pipeline_state = PipelineState(config.output)
            pipeline_state.resume(inputs)
            typer.echo(f"Resuming {completion_label} run: {config.output}")
        else:
            if config.output.is_dir() and any(config.output.iterdir()):
                raise ValueError(
                    f"Output is not empty and has no MedAI pipeline state: {config.output}"
                )
            pipeline_state = PipelineState.create(config.output, inputs)
        run_active = True
        result = workflow.invoke({"config": config})
        release_run_computation_instance(config)
    except Exception as exc:
        if "run_active" in locals() and (config.output / "manifest.json").is_file():
            cleanup_error = None
            try:
                release_run_computation_instance(config)
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
