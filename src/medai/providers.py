from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack, nullcontext
from pathlib import Path

from medai.agent_sessions import (
    archive_codex_subagents,
    pending_command_sessions,
    settle_unfinished_command_sessions,
)
from medai.artifacts import write_json
from medai.models import AgentStageResult
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
    append_transcript: bool = False,
    environment_remove: Sequence[str] = (),
    _recover_unfinished_commands: bool = True,
) -> str | None:
    """Run an agent and stream its provider JSONL transcript to disk."""
    if (
        output_schema_path is not None
        or output_last_message_path is not None
        or resume_session_id is not None
        or append_transcript
    ) and provider != "codex":
        raise ValueError(
            "Codex output schemas, session resume, and transcript append require "
            "provider='codex'"
        )
    if append_transcript and resume_session_id is not None:
        raise ValueError("Fresh-session transcript append cannot resume an existing session")
    prompt = prompt_path.read_text(encoding="utf-8")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    if (
        resume_session_id is None
        and not append_transcript
        and transcript_path.is_file()
        and transcript_path.stat().st_size
    ):
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
        subagents = transcript_path.with_name(f"{transcript_path.stem}_subagents")
        if subagents.is_dir():
            archived_subagents = archived.with_name(f"{archived.stem}_subagents")
            subagents.rename(archived_subagents)
            index_path = archived_subagents / "index.json"
            if index_path.is_file():
                index = json.loads(index_path.read_text(encoding="utf-8"))
                index["parent_transcript"] = f"../{archived.name}"
                write_json(index_path, index)
    if output_last_message_path is not None:
        output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
        output_last_message_path.unlink(missing_ok=True)

    adapter_context = nullcontext(None)
    if provider == "codex-siliconflow":
        if siliconflow_config_path is None:
            raise RuntimeError("codex-siliconflow requires a config file")
        settings = SiliconFlowConfig.from_dotenv(siliconflow_config_path)
        adapter_context = SiliconFlowAdapter(settings, artifact_dir=transcript_path.parent)

    with adapter_context as adapter, ExitStack() as cleanup:
        command = list(PROVIDER_COMMANDS[provider])
        if resume_session_id is not None:
            command.insert(2, "resume")
        command.extend(TRANSCRIPT_FLAGS[provider])
        if output_schema_path is not None:
            command.extend(["--output-schema", str(output_schema_path)])
        if output_last_message_path is not None:
            command.extend(["--output-last-message", str(output_last_message_path)])
        environment = os.environ.copy()
        for name in environment_remove:
            environment.pop(name, None)
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

        if provider == "codex":
            cleanup.callback(
                archive_codex_subagents,
                transcript_path,
                Path(environment.get("CODEX_HOME", str(Path.home() / ".codex"))),
            )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(prompt)
        process.stdin.close()
        session_id: str | None = None
        transcript_mode = "a" if resume_session_id is not None or append_transcript else "w"
        with transcript_path.open(transcript_mode, encoding="utf-8") as transcript:
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                transcript.write(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
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
        if provider.startswith("codex"):
            unfinished_commands = pending_command_sessions(transcript_path)
            if unfinished_commands and not _recover_unfinished_commands:
                raise RuntimeError(
                    f"{provider} agent exited with {len(unfinished_commands)} unfinished command "
                    f"execution(s) (transcript: {transcript_path})"
                )
            if unfinished_commands:
                recovery_session_id = resume_session_id or session_id
                if provider != "codex" or recovery_session_id is None:
                    raise RuntimeError(
                        f"{provider} agent exited with {len(unfinished_commands)} unfinished "
                        "command execution(s) and cannot resume the prior agent "
                        f"(transcript: {transcript_path})"
                    )

                def resume_agent_for_command_recovery(prompt: str) -> AgentStageResult:
                    with tempfile.TemporaryDirectory(
                        prefix="medai-agent-command-recovery-"
                    ) as recovery_dir_name:
                        recovery_dir = Path(recovery_dir_name)
                        recovery_prompt_path = recovery_dir / "prompt.md"
                        recovery_schema_path = recovery_dir / "result.schema.json"
                        recovery_result_path = recovery_dir / "result.json"
                        recovery_transcript_path = recovery_dir / "transcript.jsonl"
                        recovery_prompt_path.write_text(prompt, encoding="utf-8")
                        recovery_schema_path.write_text(
                            json.dumps(AgentStageResult.model_json_schema(), indent=2) + "\n",
                            encoding="utf-8",
                        )
                        try:
                            run_agent(
                                provider=provider,
                                prompt_path=recovery_prompt_path,
                                working_dir=working_dir,
                                transcript_path=recovery_transcript_path,
                                siliconflow_config_path=siliconflow_config_path,
                                codex_model=codex_model,
                                codex_reasoning_effort=codex_reasoning_effort,
                                output_schema_path=recovery_schema_path,
                                output_last_message_path=recovery_result_path,
                                resume_session_id=recovery_session_id,
                                environment_remove=environment_remove,
                                _recover_unfinished_commands=False,
                            )
                        finally:
                            if recovery_transcript_path.is_file():
                                with transcript_path.open("a", encoding="utf-8") as transcript:
                                    transcript.write(
                                        recovery_transcript_path.read_text(encoding="utf-8")
                                    )
                        return AgentStageResult.model_validate_json(
                            recovery_result_path.read_text(encoding="utf-8")
                        )

                settle_unfinished_command_sessions(
                    transcript_path,
                    resume_agent_for_command_recovery,
                )
        if resume_session_id is not None:
            return resume_session_id
        if output_schema_path is not None and session_id is None:
            raise RuntimeError(f"Codex did not report a thread ID (transcript: {transcript_path})")
        return session_id
