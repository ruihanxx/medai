from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from medai.config import RunConfig
from medai.pipeline_state import PipelineState, build_run_inputs
from medai.workflow import create_workflow, release_run_computation_instance

app = typer.Typer(
    name="medai",
    help="Run an evidence-bound medical paper replication workflow.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def run(
    paper: Path = typer.Option(..., "--paper", help="Path to paper.pdf"),
    output: Path = typer.Option(
        ...,
        "--output",
        help="New output directory or existing run to resume",
    ),
    provider: str = typer.Option("codex", "--provider"),
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
) -> None:
    try:
        config = RunConfig.create(
            paper=paper,
            output=output,
            provider=provider,
            repo=repo,
            data=data,
            siliconflow_config=siliconflow_config,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            smart_replicate=smart_replicate,
        )
        inputs = build_run_inputs(config)
        if (config.output / "manifest.json").exists():
            pipeline_state = PipelineState(config.output)
            pipeline_state.resume(inputs)
            typer.echo(f"Resuming MedAI run: {config.output}")
        else:
            if config.output.is_dir() and any(config.output.iterdir()):
                raise ValueError(
                    f"Output is not empty and has no MedAI pipeline state: {config.output}"
                )
            pipeline_state = PipelineState.create(config.output, inputs)
        run_active = True
        create_workflow().invoke({"config": config})
        release_run_computation_instance(config)
    except Exception as exc:
        if "run_active" in locals():
            cleanup_error = None
            try:
                release_run_computation_instance(config)
            except Exception as cleanup_exc:
                cleanup_error = str(cleanup_exc)
            message = str(exc)
            if cleanup_error:
                message = f"{message}; cleanup error: {cleanup_error}"
            pipeline_state.fail(message)
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Replication complete: {config.output / 'report' / 'reproduction_report.md'}")


if __name__ == "__main__":
    app()
