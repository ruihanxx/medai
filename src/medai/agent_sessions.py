from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from medai.models import AgentStageResult

RECOVERY_REQUEST_EVENT = "medai.command_sessions.recovery_requested"
RECOVERY_RESOLVED_EVENT = "medai.command_sessions.resolved"


@dataclass(frozen=True)
class PendingCommandSession:
    item_id: str
    command: str | None


def pending_command_sessions(transcript_path: Path) -> list[PendingCommandSession]:
    pending: dict[str, str | None] = {}
    with transcript_path.open(encoding="utf-8") as transcript:
        for line in transcript:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == RECOVERY_RESOLVED_EVENT:
                for item_id in event.get("command_ids", []):
                    if isinstance(item_id, str):
                        pending.pop(item_id, None)
                continue
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") != "command_execution":
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str):
                continue
            if event.get("type") == "item.started":
                command = item.get("command")
                pending[item_id] = command if isinstance(command, str) else None
            elif event.get("type") == "item.completed":
                pending.pop(item_id, None)
    return [
        PendingCommandSession(item_id=item_id, command=command)
        for item_id, command in pending.items()
    ]


def settle_unfinished_command_sessions(
    transcript_path: Path,
    resume_agent: Callable[[str], AgentStageResult],
) -> bool:
    pending = pending_command_sessions(transcript_path)
    if not pending:
        return False

    command_inventory = json.dumps(
        [{"item_id": item.item_id, "command": item.command} for item in pending],
        ensure_ascii=False,
        indent=2,
    )
    prompt = f"""# Unfinished command-session recovery

The previous turn ended with command executions that have no terminal event:

```json
{command_inventory}
```

This resumed CLI process cannot reuse a process-local execution handle from the
previous process. For each listed command, inspect its exact live process and
side effects. If its work is still required and the exact process is live, wait
for it in the foreground until it ends. If it is obsolete or unsafe to keep,
terminate only that exact process and confirm it has exited. If it is no longer
live, verify whether its partial effects require cleanup or completion. Rerun a
lost command only when the original stage permits it and it is demonstrably
idempotent and necessary; never repeat an ambiguous billable or destructive
operation.

Keep command execution serial during this recovery. Do not edit files, perform
another check, or return while a command is still running. After all listed
commands are settled, inspect the original stage result and required artifacts
and decide whether they are safe for orchestration to continue with its normal
handoff or artifact validation. This recovery result does not replace or change
the original stage result.

Return `{{"status":"completed","error":null}}` only when no relevant process
remains and the original result is safe for orchestration to validate. Otherwise
return `blocked` or `failed` with a non-empty error.
"""
    _append_event(
        transcript_path,
        {
            "type": RECOVERY_REQUEST_EVENT,
            "command_ids": [item.item_id for item in pending],
            "prompt": prompt,
        },
    )
    result = resume_agent(prompt)
    if result.status != "completed":
        raise RuntimeError(
            "Agent command-session recovery reported "
            f"{result.status}: {result.error} (transcript: {transcript_path})"
        )
    _append_event(
        transcript_path,
        {
            "type": RECOVERY_RESOLVED_EVENT,
            "command_ids": [item.item_id for item in pending],
            "result": result.model_dump(mode="json"),
        },
    )
    remaining = pending_command_sessions(transcript_path)
    if remaining:
        raise RuntimeError(
            "Agent command-session recovery exited with "
            f"{len(remaining)} unfinished command execution(s) "
            f"(transcript: {transcript_path})"
        )
    return True


def _append_event(transcript_path: Path, event: dict[str, object]) -> None:
    with transcript_path.open("a", encoding="utf-8") as transcript:
        transcript.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        transcript.write("\n")
