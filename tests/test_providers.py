import io
from pathlib import Path

import pytest

from medai.models import ReplicationCommand, ReplicationExperimentHandoff
from medai.providers import run_agent
from medai.siliconflow_adapter import (
    SiliconFlowConfig,
    chat_to_response_items,
    responses_to_chat,
)


class FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.stdin = OpenStringIO()
        self.stdout = io.StringIO(
            '{"type":"thread.started","thread_id":"thread-123"}\n' '{"type":"done"}\n'
        )

    def wait(self):
        return 0


class FakeUnfinishedCommandProcess(FakeProcess):
    def __init__(self, command, **kwargs):
        super().__init__(command, **kwargs)
        self.stdout = io.StringIO(
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            '{"type":"item.started","item":{"id":"item-1",'
            '"type":"command_execution","status":"in_progress"}}\n'
            '{"type":"turn.completed"}\n'
        )


class OpenStringIO(io.StringIO):
    def close(self):
        return


def test_codex_prompt_uses_stdin_and_writes_transcript(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setenv("MEDAI_HOST_REPO", "/hidden/repository")

    def fake_popen(command, **kwargs):
        captured["environment"] = kwargs["env"]
        captured["process"] = FakeProcess(command, **kwargs)
        return captured["process"]

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do the work", encoding="utf-8")
    transcript = tmp_path / "agent_transcript.jsonl"
    transcript.write_text('{"type":"interrupted"}\n', encoding="utf-8")

    run_agent(
        provider="codex",
        prompt_path=prompt,
        working_dir=tmp_path,
        transcript_path=transcript,
        siliconflow_config_path=None,
        codex_model="gpt-5.6-terra",
        codex_reasoning_effort="high",
        environment_remove=("MEDAI_HOST_REPO",),
    )

    assert captured["process"].command[-1] == "-"
    assert captured["process"].command[-5:-1] == [
        "--model",
        "gpt-5.6-terra",
        "--config",
        'model_reasoning_effort="high"',
    ]
    assert captured["process"].stdin.getvalue() == "do the work"
    assert "MEDAI_HOST_REPO" not in captured["environment"]
    assert '"type":"done"' in transcript.read_text(encoding="utf-8")
    assert '"type":"interrupted"' in (tmp_path / "agent_transcript.attempt-1.jsonl").read_text(
        encoding="utf-8"
    )


def test_codex_records_tool_error_output_without_treating_it_as_agent_status(
    tmp_path: Path, monkeypatch
):
    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        process.stdout = io.StringIO(
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            "apply_patch verification failed\n"
            '"reported partition arithmetic"\n'
            '{"type":"item.started","item":{"id":"item-1",'
            '"type":"command_execution","status":"in_progress"}}\n'
            '{"type":"item.completed","item":{"id":"item-1",'
            '"type":"command_execution","status":"failed",'
            '"aggregated_output":"patch context did not match"}}\n'
            '{"type":"turn.completed"}\n'
        )
        return process

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("repair a tool failure", encoding="utf-8")
    transcript = tmp_path / "agent_transcript.jsonl"

    assert (
        run_agent(
            provider="codex",
            prompt_path=prompt,
            working_dir=tmp_path,
            transcript_path=transcript,
            siliconflow_config_path=None,
        )
        == "thread-123"
    )
    transcript_text = transcript.read_text(encoding="utf-8")
    assert "apply_patch verification failed" in transcript_text
    assert '"reported partition arithmetic"' in transcript_text


@pytest.mark.parametrize("confined", [False, True])
def test_codex_command_turn_uses_schema_and_explicit_session_resume(tmp_path: Path, monkeypatch, confined):
    processes = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("return a command", encoding="utf-8")
    transcript = tmp_path / "replication_transcript.jsonl"
    schema = tmp_path / "command.schema.json"
    schema.write_text("{}\n", encoding="utf-8")
    initial_result = tmp_path / "command_001.json"

    session_id = run_agent(
        provider="codex",
        prompt_path=prompt,
        working_dir=tmp_path,
        transcript_path=transcript,
        siliconflow_config_path=None,
        output_schema_path=schema,
        output_last_message_path=initial_result,
        confine_to_working_dir=confined,
    )

    assert session_id == "thread-123"
    assert processes[0].command[:2] == ["codex", "exec"]
    assert "resume" not in processes[0].command
    assert ["--output-schema", str(schema)] == processes[0].command[
        processes[0].command.index("--output-schema") : processes[0].command.index(
            "--output-schema"
        )
        + 2
    ]
    assert processes[0].command[-1] == "-"

    resume_prompt = tmp_path / "resume.md"
    resume_prompt.write_text("inspect the saved result", encoding="utf-8")
    resumed_result = tmp_path / "command_002.json"
    resumed = run_agent(
        provider="codex",
        prompt_path=resume_prompt,
        working_dir=tmp_path,
        transcript_path=transcript,
        siliconflow_config_path=None,
        output_schema_path=schema,
        output_last_message_path=resumed_result,
        resume_session_id=session_id,
        confine_to_working_dir=confined,
    )

    assert resumed == "thread-123"
    assert processes[1].command[:3] == ["codex", "exec", "resume"]
    assert processes[1].command[-2:] == ["thread-123", "-"]
    assert "--last" not in processes[1].command
    assert transcript.read_text(encoding="utf-8").count('"type":"done"') == 2
    assert not (tmp_path / "replication_transcript.attempt-1.jsonl").exists()
    for process in processes:
        assert ('sandbox_mode="workspace-write"' in process.command) is confined
        assert ("--dangerously-bypass-approvals-and-sandbox" in process.command) is not confined


def test_codex_fresh_session_can_append_existing_transcript(tmp_path: Path, monkeypatch):
    processes = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("continue in a fresh session", encoding="utf-8")
    transcript = tmp_path / "replication_transcript.jsonl"
    transcript.write_text('{"type":"old-session"}\n', encoding="utf-8")

    session_id = run_agent(
        provider="codex",
        prompt_path=prompt,
        working_dir=tmp_path,
        transcript_path=transcript,
        siliconflow_config_path=None,
        append_transcript=True,
    )

    assert session_id == "thread-123"
    assert "resume" not in processes[0].command
    transcript_text = transcript.read_text(encoding="utf-8")
    assert '"type":"old-session"' in transcript_text
    assert '"thread_id":"thread-123"' in transcript_text
    assert not (tmp_path / "replication_transcript.attempt-1.jsonl").exists()


def test_codex_turn_resumes_to_settle_unfinished_command_execution(
    tmp_path: Path, monkeypatch
):
    processes = []

    def fake_popen(command, **kwargs):
        if not processes:
            process = FakeUnfinishedCommandProcess(command, **kwargs)
            result_index = command.index("--output-last-message") + 1
            Path(command[result_index]).write_text(
                '{"original":"stage-result"}\n', encoding="utf-8"
            )
        else:
            process = FakeProcess(command, **kwargs)
            result_index = command.index("--output-last-message") + 1
            Path(command[result_index]).write_text(
                '{"status":"completed","error":null}\n', encoding="utf-8"
            )
        processes.append(process)
        return process

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("wait for commands", encoding="utf-8")
    transcript = tmp_path / "transcript.jsonl"
    schema = tmp_path / "stage.schema.json"
    schema.write_text("{}\n", encoding="utf-8")
    stage_result = tmp_path / "stage-result.json"

    assert (
        run_agent(
            provider="codex",
            prompt_path=prompt,
            working_dir=tmp_path,
            transcript_path=transcript,
            siliconflow_config_path=None,
            output_schema_path=schema,
            output_last_message_path=stage_result,
        )
        == "thread-123"
    )
    assert len(processes) == 2
    assert processes[1].command[:3] == ["codex", "exec", "resume"]
    assert "item-1" in processes[1].stdin.getvalue()
    transcript_text = transcript.read_text(encoding="utf-8")
    assert '"type":"medai.command_sessions.recovery_requested"' in transcript_text
    assert '"type":"medai.command_sessions.resolved"' in transcript_text
    assert stage_result.read_text(encoding="utf-8") == '{"original":"stage-result"}\n'


def test_codex_turn_rejects_unfinished_recovery_command(tmp_path: Path, monkeypatch):
    processes = []

    def fake_popen(command, **kwargs):
        process = FakeUnfinishedCommandProcess(command, **kwargs)
        if processes:
            process.stdout = io.StringIO(
                '{"type":"item.started","item":{"id":"item-2",'
                '"type":"command_execution","status":"in_progress"}}\n'
                '{"type":"turn.completed"}\n'
            )
        processes.append(process)
        return process

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("wait for commands", encoding="utf-8")

    with pytest.raises(RuntimeError, match="1 unfinished command execution"):
        run_agent(
            provider="codex",
            prompt_path=prompt,
            working_dir=tmp_path,
            transcript_path=tmp_path / "transcript.jsonl",
            siliconflow_config_path=None,
        )


def test_replication_command_requires_exactly_one_nonblank_field():
    assert (
        ReplicationCommand.model_validate({"command": "python run.py"}).command == "python run.py"
    )
    with pytest.raises(ValueError, match="blank"):
        ReplicationCommand.model_validate({"command": "  \n"})
    with pytest.raises(ValueError, match="Extra inputs"):
        ReplicationCommand.model_validate({"command": "true", "status": "done"})


def test_replication_experiment_handoff_requires_complete_command_contract():
    request = ReplicationExperimentHandoff.model_validate(
        {
            "status": "command",
            "command": "python train.py",
            "hard_timeout_seconds": 3600,
            "progress_command": "python progress.py",
            "graceful_stop_command": "python stop.py",
            "error": None,
        }
    )
    assert request.hard_timeout_seconds == 3600

    rollover = ReplicationExperimentHandoff.model_validate(
        {
            "status": "context_exhausted",
            "command": None,
            "hard_timeout_seconds": None,
            "progress_command": None,
            "graceful_stop_command": None,
            "error": None,
        }
    )
    assert rollover.status == "context_exhausted"

    with pytest.raises(ValueError, match="progress"):
        ReplicationExperimentHandoff.model_validate(
            {
                "status": "command",
                "command": "python train.py",
                "hard_timeout_seconds": 3600,
                "progress_command": "",
                "graceful_stop_command": "python stop.py",
                "error": None,
            }
        )
    with pytest.raises(ValueError, match="null commands"):
        ReplicationExperimentHandoff.model_validate(
            {
                "status": "completed",
                "command": "true",
                "hard_timeout_seconds": None,
                "progress_command": None,
                "graceful_stop_command": None,
                "error": None,
            }
        )
    context_payload = rollover.model_dump()
    for field, value, message in (
        ("command", "python experiment.py", "null commands"),
        ("hard_timeout_seconds", 30, "null timeout and error"),
        ("error", "context is full", "null timeout and error"),
    ):
        with pytest.raises(ValueError, match=message):
            ReplicationExperimentHandoff.model_validate(
                {**context_payload, field: value}
            )


def test_siliconflow_key_is_removed_from_child_environment():
    settings = SiliconFlowConfig(api_key="secret")
    from medai.siliconflow_adapter import SiliconFlowAdapter

    adapter = SiliconFlowAdapter(settings, artifact_dir=Path("/tmp"))
    environment = adapter.child_environment(
        {"SILICONFLOW_API_KEY": "secret", "ALSO_SECRET": "secret", "SAFE": "value"}
    )
    assert "SILICONFLOW_API_KEY" not in environment
    assert "ALSO_SECRET" not in environment
    assert environment["SAFE"] == "value"


def test_siliconflow_reasoning_effort_is_validated(tmp_path: Path):
    config_path = tmp_path / "siliconflow.env"
    config_path.write_text(
        "SILICONFLOW_API_KEY=secret\n"
        "CODEX_CLI_SILICONFLOW_REASONING_EFFORT=max\n",
        encoding="utf-8",
    )
    assert SiliconFlowConfig.from_dotenv(config_path).reasoning_effort == "max"

    config_path.write_text(
        "SILICONFLOW_API_KEY=secret\n"
        "CODEX_CLI_SILICONFLOW_REASONING_EFFORT=medium\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be 'high' or 'max'"):
        SiliconFlowConfig.from_dotenv(config_path)


def test_responses_and_tool_calls_translate():
    chat = responses_to_chat(
        {
            "instructions": "Be exact.",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Inspect files"}],
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "description": "Run a command",
                    "parameters": {"type": "object"},
                }
            ],
        },
        reasoning_effort="max",
    )
    assert chat["messages"][0]["role"] == "system"
    assert chat["messages"][1]["content"] == "Inspect files"
    assert chat["tools"][0]["function"]["name"] == "shell"
    assert chat["reasoning_effort"] == "max"

    items = chat_to_response_items(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "shell", "arguments": '{"cmd":"ls"}'},
                            }
                        ],
                    }
                }
            ]
        }
    )
    assert items[0]["type"] == "function_call"
    assert items[0]["call_id"] == "call_1"
