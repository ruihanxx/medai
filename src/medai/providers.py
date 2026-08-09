from __future__ import annotations

import json
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
    ],
    "codex": [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ],
    "codex-siliconflow": [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
    ],
}

TRANSCRIPT_FLAGS = {
    "claude": ["--verbose", "--output-format", "stream-json"],
    "codex": ["--json"],
    "codex-siliconflow": ["--json"],
}


def run_agent(
    *,
    provider: str,
    prompt_path: Path,
    working_dir: Path,
    transcript_path: Path,
    siliconflow_config_path: Path | None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    output_schema_path: Path | None = None,
    output_last_message_path: Path | None = None,
    resume_session_id: str | None = None,
) -> str | None:
    """Run an agent and stream its provider JSONL transcript to disk."""
    if (
        output_schema_path is not None
        or output_last_message_path is not None
        or resume_session_id is not None
    ) and provider != "codex":
        raise ValueError("Codex output schemas and session resume require provider='codex'")
    prompt = prompt_path.read_text(encoding="utf-8")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    if resume_session_id is None and transcript_path.is_file() and transcript_path.stat().st_size:
        attempt = 1
        archived = transcript_path.with_name(
            f"{transcript_path.stem}.attempt-{attempt}{transcript_path.suffix}"
        )
        while archived.exists():
            attempt += 1
            archived = transcript_path.with_name(
                f"{transcript_path.stem}.attempt-{attempt}{transcript_path.suffix}"
            )
        transcript_path.replace(archived)
    if output_last_message_path is not None:
        output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
        output_last_message_path.unlink(missing_ok=True)

    adapter_context = nullcontext(None)
    if provider == "codex-siliconflow":
        if siliconflow_config_path is None:
            raise RuntimeError("codex-siliconflow requires a config file")
        settings = SiliconFlowConfig.from_dotenv(siliconflow_config_path)
        adapter_context = SiliconFlowAdapter(settings, artifact_dir=transcript_path.parent)

    with adapter_context as adapter:
        command = list(PROVIDER_COMMANDS[provider])
        if resume_session_id is not None:
            command.insert(2, "resume")
        command.extend(TRANSCRIPT_FLAGS[provider])
        if output_schema_path is not None:
            command.extend(["--output-schema", str(output_schema_path)])
        if output_last_message_path is not None:
            command.extend(["--output-last-message", str(output_last_message_path)])
        environment = os.environ.copy()
        if adapter is not None:
            command.extend(adapter.codex_args())
            environment = adapter.child_environment(environment)
        if provider == "codex":
            if codex_model:
                command.extend(["--model", codex_model])
            if codex_reasoning_effort:
                command.extend(["--config", f'model_reasoning_effort="{codex_reasoning_effort}"'])
        if provider.startswith("codex"):
            if resume_session_id is not None:
                command.append(resume_session_id)
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
        session_id: str | None = None
        transcript_mode = "a" if resume_session_id is not None else "w"
        with transcript_path.open(transcript_mode, encoding="utf-8") as transcript:
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                transcript.write(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "thread.started" and isinstance(
                    event.get("thread_id"), str
                ):
                    session_id = event["thread_id"]
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(
                f"{provider} agent failed with exit code {return_code} "
                f"(transcript: {transcript_path})"
            )
        if resume_session_id is not None:
            return resume_session_id
        if output_schema_path is not None and session_id is None:
            raise RuntimeError(f"Codex did not report a thread ID (transcript: {transcript_path})")
        return session_id
