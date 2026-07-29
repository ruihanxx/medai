from __future__ import annotations

import os
import subprocess
from contextlib import nullcontext
from pathlib import Path

from medai.siliconflow_adapter import SiliconFlowAdapter, SiliconFlowConfig

PROVIDER_COMMANDS = {
    "claude": [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--verbose",
        "--output-format",
        "stream-json",
    ],
    "codex": [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--json",
    ],
    "codex-siliconflow": [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--json",
    ],
}


def run_agent(
    *,
    provider: str,
    prompt_path: Path,
    working_dir: Path,
    log_path: Path,
    siliconflow_config_path: Path | None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
) -> None:
    prompt = prompt_path.read_text(encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    adapter_context = nullcontext(None)
    if provider == "codex-siliconflow":
        if siliconflow_config_path is None:
            raise RuntimeError("codex-siliconflow requires a config file")
        settings = SiliconFlowConfig.from_dotenv(siliconflow_config_path)
        adapter_context = SiliconFlowAdapter(settings, artifact_dir=log_path.parent)

    with adapter_context as adapter:
        command = list(PROVIDER_COMMANDS[provider])
        environment = os.environ.copy()
        if adapter is not None:
            command.extend(adapter.codex_args())
            environment = adapter.child_environment(environment)
        if provider == "codex":
            if codex_model:
                command.extend(["--model", codex_model])
            if codex_reasoning_effort:
                command.extend(
                    ["--config", f'model_reasoning_effort="{codex_reasoning_effort}"']
                )
        if provider.startswith("codex"):
            command.append("-")

        try:
            process = subprocess.Popen(
                command,
                cwd=working_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Provider CLI is not installed: {command[0]}") from exc

        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(prompt)
        process.stdin.close()
        with log_path.open("w", encoding="utf-8") as log:
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                log.write(line)
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"{provider} agent failed with exit code {return_code}")
