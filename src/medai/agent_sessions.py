from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from medai.artifacts import write_json
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


def archive_codex_subagents(transcript_path: Path, codex_home: Path) -> None:
    """Archive this transcript's descendant rollouts before the runtime HOME disappears."""
    if not transcript_path.is_file():
        return
    archive_dir = transcript_path.with_name(f"{transcript_path.stem}_subagents")
    index_path = archive_dir / "index.json"
    agents = {}
    indexed_lines = 0
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        agents = {agent["thread_id"]: agent for agent in index["agents"]}
        indexed_lines = index["transcript_lines"]
    roots = set()
    reported_statuses = {}
    transcript_lines = 0
    with transcript_path.open(encoding="utf-8") as transcript:
        for transcript_lines, line in enumerate(transcript, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                roots.add(event["thread_id"])
            if transcript_lines <= indexed_lines:
                continue
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") != "collab_tool_call":
                continue
            for thread_id in item.get("receiver_thread_ids", []):
                if "spawn" in item.get("tool", ""):
                    agent = agents.setdefault(thread_id, {"thread_id": thread_id})
                    agent["parent_thread_id"] = item.get("sender_thread_id")
                    if item.get("prompt"):
                        agent["task"] = item["prompt"]
                state = (item.get("agents_states") or {}).get(thread_id)
                if isinstance(state, dict) and state.get("status"):
                    reported_statuses[thread_id] = state["status"]
    if not roots:
        return

    # Read only metadata while discovering ancestry, not unrelated agent histories.
    rollouts = {}
    for directory in (codex_home / "sessions", codex_home / "archived_sessions"):
        for path in directory.rglob("*.jsonl"):
            try:
                with path.open(encoding="utf-8") as source:
                    event = json.loads(source.readline())
            except (OSError, ValueError):
                continue
            if not isinstance(event, dict) or event.get("type") != "session_meta":
                continue
            metadata = event.get("payload", {})
            origin = metadata.get("source")
            if not isinstance(origin, dict):
                continue
            subagent = origin.get("subagent")
            spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
            if not isinstance(spawn, dict):
                continue
            thread_id = metadata.get("id")
            parent_id = metadata.get("parent_thread_id") or spawn.get("parent_thread_id")
            if isinstance(thread_id, str) and isinstance(parent_id, str):
                rollouts[thread_id] = (path, parent_id, metadata)

    related = set(roots)
    while True:
        descendants = {
            thread_id for thread_id, (_, parent_id, _) in rollouts.items()
            if parent_id in related
        } | {
            thread_id for thread_id, agent in agents.items()
            if agent.get("parent_thread_id") in related
        }
        if descendants <= related:
            break
        related.update(descendants)
    for thread_id in sorted(related - roots):
        # Native thread IDs are UUIDs; never use arbitrary tool text as an output path.
        UUID(thread_id)
        agent = agents.setdefault(thread_id, {"thread_id": thread_id})
        agent.setdefault("task", None)
        agent.setdefault("task_log_line", None)
        agent.setdefault("status", "unknown")
        destination = archive_dir / f"{thread_id}.jsonl"
        rollout_status = None
        if thread_id in rollouts:
            source, parent_id, metadata = rollouts[thread_id]
            agent["parent_thread_id"] = parent_id
            agent["name"] = metadata.get("agent_path") or metadata.get("agent_nickname")
            archive_dir.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            indexed_log_lines = agent.get("log_lines", 0)
            with destination.open(encoding="utf-8") as rollout:
                for number, line in enumerate(rollout, 1):
                    if not line.endswith("\n"):
                        break
                    agent["log_lines"] = number
                    if number <= indexed_log_lines:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    payload = event.get("payload", {})
                    # A full-history fork may contain events predating this child.
                    if event.get("timestamp", "") < metadata.get("timestamp", ""):
                        continue
                    if event.get("type") == "event_msg":
                        event_type = payload.get("type")
                        status = {
                            "task_started": "running",
                            "task_complete": "completed",
                            "turn_aborted": "interrupted",
                        }.get(event_type)
                        if status:
                            agent["status"] = status
                            rollout_status = status
                        if event_type == "user_message" and agent["task"] is None:
                            agent["task"] = payload.get("message")
                            agent["task_log_line"] = number
                    elif (
                        event.get("type") == "response_item"
                        and payload.get("type") == "agent_message"
                        and agent["task_log_line"] is None
                    ):
                        content = payload.get("content", [])
                        text = "\n".join(part.get("text", "") for part in content)
                        if "Message Type: NEW_TASK" in text:
                            agent["task_log_line"] = number
                            if all(part.get("type") != "encrypted_content" for part in content):
                                agent["task"] = agent["task"] or text
        reported_status = reported_statuses.get(thread_id)
        if reported_status and (
            reported_status not in {"running", "pending_init"} or rollout_status is None
        ):
            agent["status"] = reported_status
        agent["log_path"] = destination.name if destination.is_file() else None
        agent["log_status"] = "archived" if destination.is_file() else "missing"

    records = [agents[key] for key in sorted(related - roots)]
    if records:
        temporary = index_path.with_suffix(".tmp")
        write_json(temporary, {
            "stage": transcript_path.stem.removesuffix("_transcript"),
            "parent_transcript": f"../{transcript_path.name}",
            "transcript_lines": transcript_lines,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "agents": records,
        })
        temporary.replace(index_path)
