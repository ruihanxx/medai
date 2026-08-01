from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from medai.artifacts import fail_manifest, initialize_manifest
from medai.config import RunConfig
from medai.workflow import create_workflow, release_run_computation_instance

app = typer.Typer(
    name="medai",
    help="Run an evidence-bound medical paper replication workflow.",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def run(
    paper: Path = typer.Option(..., "--paper", help="Path to paper.pdf"),
    output: Path = typer.Option(..., "--output", help="Writable output directory"),
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
        if (config.output / "manifest.json").exists():
            raise ValueError(
                f"Output already contains a medai run: {config.output}. Use a new output directory."
            )
        config.output.mkdir(parents=True, exist_ok=True)
        initialize_manifest(
            config.output,
            {
                "paper": str(config.paper),
                "repo": str(config.repo) if config.repo else None,
                "data": str(config.data) if config.data else None,
                "provider": config.provider,
                "codex_model": config.codex_model,
                "codex_reasoning_effort": config.codex_reasoning_effort,
                "smart_replicate": config.smart_replicate,
            },
        )
        create_workflow().invoke({"config": config})
        release_run_computation_instance(config)
    except Exception as exc:
        if "config" in locals() and (config.output / "manifest.json").exists():
            cleanup_error = None
            try:
                release_run_computation_instance(config)
            except Exception as cleanup_exc:
                cleanup_error = str(cleanup_exc)
            message = str(exc)
            if cleanup_error:
                message = f"{message}; cleanup error: {cleanup_error}"
            fail_manifest(config.output, message)
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Replication complete: {config.output / 'report' / 'reproduction_report.md'}")


if __name__ == "__main__":
    app()
