from __future__ import annotations

import json
from pathlib import Path

import pytest

from medai.artifacts import write_json
from medai.config import RunConfig
from medai.models import (
    GraphNode,
    ReplicationExperimentHandoff,
    SmartReplicateLog,
    validate_smart_replicate_log,
)
from medai.workflow import (
    _run_replication_experiment,
    _run_replication_experiment_handoff,
)


def test_smart_replicate_is_claim_keyed_and_requires_paper_anchor() -> None:
    claim = GraphNode(
        id="C1",
        inputs=["V1"],
        method={"comparison": "difference"},
        paper_result={"auroc": 0.8},
        provenance=[],
    )
    log = SmartReplicateLog.model_validate(
        {
            "claim_id": "C1",
            "baseline_result": {"auroc": 0.77},
            "paper_result": {"auroc": 0.8},
            "rounds": [],
            "final_result": {"auroc": 0.79},
        }
    )
    validate_smart_replicate_log(claim, log)
    assert Path("replication/claims") / claim.id / "smart_replicate_log.json" == Path(
        "replication/claims/C1/smart_replicate_log.json"
    )


def test_replication_experiment_timeout_stops_then_collects_light_progress(
    tmp_path: Path,
) -> None:
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    request = ReplicationExperimentHandoff.model_validate(
        {
            "status": "command",
            "command": (
                "printf '{\"epoch\":2,\"batch\":40,\"throughput\":3.5}' > progress.json; "
                "echo $$ > experiment.pid; sleep 30"
            ),
            "hard_timeout_seconds": 1,
            "progress_command": "cat progress.json",
            "graceful_stop_command": "kill -TERM -- -$(cat experiment.pid)",
            "error": None,
        }
    )
    result_path = tmp_path / "commands" / "command_001_result.json"

    result = _run_replication_experiment(
        request,
        codebase_dir=codebase,
        log_path=tmp_path / "commands" / "command_001.log",
        result_path=result_path,
    )

    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["progress"] == {"epoch": 2, "batch": 40, "throughput": 3.5}
    assert Path(result["graceful_stop_result_path"]).is_file()
    assert Path(result["progress_result_path"]).is_file()
    assert json.loads(result_path.read_text(encoding="utf-8"))["progress"] == result[
        "progress"
    ]


def test_replication_experiment_handoff_resumes_with_current_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    config = RunConfig(paper=paper, output=output, provider="codex")
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    prompt_path = output / "prompts" / "replicate.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("run replication", encoding="utf-8")
    transcript_path = output / "replication" / "replication_transcript.jsonl"
    agent_calls = []

    def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        if len(agent_calls) == 1:
            payload = {
                "status": "command",
                "command": "python train.py",
                "hard_timeout_seconds": 3600,
                "progress_command": "python progress.py",
                "graceful_stop_command": "python stop.py",
                "error": None,
            }
        else:
            payload = {
                "status": "completed",
                "command": None,
                "hard_timeout_seconds": None,
                "progress_command": None,
                "graceful_stop_command": None,
                "error": None,
            }
        write_json(kwargs["output_last_message_path"], payload)
        return "thread-123"

    def fake_experiment(request, *, codebase_dir, log_path, result_path):
        log_path.write_text("complete\n", encoding="utf-8")
        progress_path = result_path.with_name("command_001_progress_result.json")
        progress_log_path = result_path.with_name("command_001_progress.log")
        write_json(progress_path, {"exit_code": 0, "log_path": str(progress_log_path)})
        progress_log_path.write_text('{"epoch":2,"throughput":3.5}\n', encoding="utf-8")
        result = {
            "exit_code": 0,
            "duration_seconds": 12.0,
            "hard_timeout_seconds": request.hard_timeout_seconds,
            "timed_out": False,
            "graceful_stop_result_path": None,
            "progress_result_path": str(progress_path),
            "progress_log_path": str(progress_log_path),
            "progress": {"epoch": 2, "throughput": 3.5},
        }
        write_json(result_path, result)
        return result

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    monkeypatch.setattr("medai.workflow._run_replication_experiment", fake_experiment)

    outputs = _run_replication_experiment_handoff(
        config=config,
        codebase_dir=codebase,
        prompt_path=prompt_path,
        transcript_path=transcript_path,
        artifact_paths=[output / "replication" / "replication_log.json"],
        validate=lambda: ["validated.json"],
        render_new_session_prompt=lambda *_args: pytest.fail(
            "one handoff must not roll over the session"
        ),
    )

    assert outputs == ["validated.json"]
    assert agent_calls[0]["resume_session_id"] is None
    assert agent_calls[1]["resume_session_id"] == "thread-123"
    current_handoff_path = agent_calls[1]["prompt_path"]
    assert current_handoff_path == (
        output / "replication" / "commands" / "current_handoff.json"
    )
    current_handoff = json.loads(current_handoff_path.read_text(encoding="utf-8"))
    assert current_handoff["handoff_id"] == "command_001"
    assert current_handoff["status"] == "terminal"
    assert current_handoff["request_path"].endswith("command_001.json")
    assert current_handoff["result_path"].endswith("command_001_result.json")
    assert "progress" not in current_handoff


def test_replication_handoff_starts_fresh_session_after_six_terminal_experiments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    config = RunConfig(paper=paper, output=output, provider="codex")
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    prompt_path = output / "prompts" / "replicate.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("run replication", encoding="utf-8")
    transcript_path = output / "replication" / "replication_transcript.jsonl"
    agent_calls = []
    fresh_session_ids = iter(["thread-1", "thread-2"])
    rollover_calls = []

    def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        command_number = len(agent_calls)
        payload = (
            {
                "status": "command",
                "command": f"python experiment_{command_number}.py",
                "hard_timeout_seconds": 3600,
                "progress_command": "python progress.py",
                "graceful_stop_command": "python stop.py",
                "error": None,
            }
            if command_number <= 6
            else {
                "status": "completed",
                "command": None,
                "hard_timeout_seconds": None,
                "progress_command": None,
                "graceful_stop_command": None,
                "error": None,
            }
        )
        write_json(kwargs["output_last_message_path"], payload)
        return kwargs["resume_session_id"] or next(fresh_session_ids)

    experiment_outcomes = iter(
        [(0, False), (1, False), (124, True), (0, False), (2, False), (0, False)]
    )

    def fake_experiment(request, *, codebase_dir, log_path, result_path):
        exit_code, timed_out = next(experiment_outcomes)
        log_path.write_text("terminal\n", encoding="utf-8")
        result = {"exit_code": exit_code, "timed_out": timed_out}
        write_json(result_path, result)
        return result

    def render_fresh_session(session_number, reason, current_handoff_path):
        rollover_calls.append((session_number, reason, current_handoff_path))
        path = output / "prompts" / f"replicate_session_{session_number:03d}.md"
        path.write_text(
            f"# Replication Agent Session\nreason={reason}\n"
            f"handoff={current_handoff_path}\n",
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    monkeypatch.setattr("medai.workflow._run_replication_experiment", fake_experiment)

    outputs = _run_replication_experiment_handoff(
        config=config,
        codebase_dir=codebase,
        prompt_path=prompt_path,
        transcript_path=transcript_path,
        artifact_paths=[output / "replication" / "replication_log.json"],
        validate=lambda: ["validated.json"],
        render_new_session_prompt=render_fresh_session,
    )

    assert outputs == ["validated.json"]
    assert [call["resume_session_id"] for call in agent_calls[:6]] == [
        None,
        "thread-1",
        "thread-1",
        "thread-1",
        "thread-1",
        "thread-1",
    ]
    assert agent_calls[6]["resume_session_id"] is None
    assert agent_calls[6]["append_transcript"] is True
    assert agent_calls[6]["prompt_path"].name == "replicate_session_002.md"
    assert len(rollover_calls) == 1
    assert rollover_calls[0][0:2] == (2, "handoff_limit")
    assert rollover_calls[0][2].name == "current_handoff.json"


def test_replication_context_exhaustion_rolls_over_and_resets_after_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    config = RunConfig(paper=paper, output=output, provider="codex")
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    prompt_path = output / "prompts" / "replicate.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("run replication", encoding="utf-8")
    responses = iter(["context_exhausted", "command", "context_exhausted", "completed"])
    fresh_session_ids = iter(["thread-1", "thread-2", "thread-3"])
    agent_calls = []
    rollover_calls = []

    def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        status = next(responses)
        payload = {
            "status": status,
            "command": "python train.py" if status == "command" else None,
            "hard_timeout_seconds": 3600 if status == "command" else None,
            "progress_command": "python progress.py" if status == "command" else None,
            "graceful_stop_command": "python stop.py" if status == "command" else None,
            "error": None,
        }
        write_json(kwargs["output_last_message_path"], payload)
        return kwargs["resume_session_id"] or next(fresh_session_ids)

    def fake_experiment(request, *, codebase_dir, log_path, result_path):
        log_path.write_text("complete\n", encoding="utf-8")
        result = {"exit_code": 0, "timed_out": False}
        write_json(result_path, result)
        return result

    def render_fresh_session(session_number, reason, current_handoff_path):
        rollover_calls.append((session_number, reason, current_handoff_path))
        path = output / "prompts" / f"replicate_session_{session_number:03d}.md"
        path.write_text("# Replication Agent Session\n", encoding="utf-8")
        return path

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    monkeypatch.setattr("medai.workflow._run_replication_experiment", fake_experiment)

    outputs = _run_replication_experiment_handoff(
        config=config,
        codebase_dir=codebase,
        prompt_path=prompt_path,
        transcript_path=output / "replication" / "replication_transcript.jsonl",
        artifact_paths=[output / "replication" / "replication_log.json"],
        validate=lambda: ["validated.json"],
        render_new_session_prompt=render_fresh_session,
    )

    assert outputs == ["validated.json"]
    assert [call["resume_session_id"] for call in agent_calls] == [
        None,
        None,
        "thread-2",
        None,
    ]
    assert [call[1] for call in rollover_calls] == [
        "context_exhausted",
        "context_exhausted",
    ]
    assert rollover_calls[0][2] is None
    assert rollover_calls[1][2].name == "current_handoff.json"


def test_replication_rejects_two_consecutive_context_exhaustions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    config = RunConfig(paper=paper, output=output, provider="codex")
    codebase = output / "codegen" / "codebase"
    codebase.mkdir(parents=True)
    prompt_path = output / "prompts" / "replicate.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("run replication", encoding="utf-8")
    agent_calls = []

    def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        write_json(
            kwargs["output_last_message_path"],
            {
                "status": "context_exhausted",
                "command": None,
                "hard_timeout_seconds": None,
                "progress_command": None,
                "graceful_stop_command": None,
                "error": None,
            },
        )
        return f"thread-{len(agent_calls)}"

    def render_fresh_session(session_number, reason, current_handoff_path):
        path = output / "prompts" / f"replicate_session_{session_number:03d}.md"
        path.write_text("# Replication Agent Session\n", encoding="utf-8")
        return path

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)

    with pytest.raises(RuntimeError, match="two consecutive fresh sessions"):
        _run_replication_experiment_handoff(
            config=config,
            codebase_dir=codebase,
            prompt_path=prompt_path,
            transcript_path=output / "replication" / "replication_transcript.jsonl",
            artifact_paths=[output / "replication" / "replication_log.json"],
            validate=lambda: ["validated.json"],
            render_new_session_prompt=render_fresh_session,
        )

    assert agent_calls[1]["resume_session_id"] is None
    assert agent_calls[1]["append_transcript"] is True


def test_replication_prompt_reserves_handoff_for_result_producing_work() -> None:
    prompt = (
        Path(__file__).parents[1] / "templates" / "replication" / "session_instructions.md"
    ).read_text(encoding="utf-8")

    assert "must never be returned as a handoff" in prompt
    assert "Never hand off the node-free" in prompt
    assert "step, an environment or storage probe" in prompt
    assert '"status":"context_exhausted"' in prompt
    assert "Fresh-session continuation" in prompt
