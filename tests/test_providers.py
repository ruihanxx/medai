import io
from pathlib import Path

import pytest

from medai.models import ReplicationCommand
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


class OpenStringIO(io.StringIO):
    def close(self):
        return


def test_codex_prompt_uses_stdin_and_writes_transcript(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
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
    )

    assert captured["process"].command[-1] == "-"
    assert captured["process"].command[-5:-1] == [
        "--model",
        "gpt-5.6-terra",
        "--config",
        'model_reasoning_effort="high"',
    ]
    assert captured["process"].stdin.getvalue() == "do the work"
    assert '"type":"done"' in transcript.read_text(encoding="utf-8")
    assert '"type":"interrupted"' in (tmp_path / "agent_transcript.attempt-1.jsonl").read_text(
        encoding="utf-8"
    )


def test_codex_command_turn_uses_schema_and_explicit_session_resume(tmp_path: Path, monkeypatch):
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
    )

    assert resumed == "thread-123"
    assert processes[1].command[:3] == ["codex", "exec", "resume"]
    assert processes[1].command[-2:] == ["thread-123", "-"]
    assert "--last" not in processes[1].command
    assert transcript.read_text(encoding="utf-8").count('"type":"done"') == 2
    assert not (tmp_path / "replication_transcript.attempt-1.jsonl").exists()


def test_replication_command_requires_exactly_one_nonblank_field():
    assert (
        ReplicationCommand.model_validate({"command": "python run.py"}).command == "python run.py"
    )
    with pytest.raises(ValueError, match="blank"):
        ReplicationCommand.model_validate({"command": "  \n"})
    with pytest.raises(ValueError, match="Extra inputs"):
        ReplicationCommand.model_validate({"command": "true", "status": "done"})


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
        }
    )
    assert chat["messages"][0]["role"] == "system"
    assert chat["messages"][1]["content"] == "Inspect files"
    assert chat["tools"][0]["function"]["name"] == "shell"

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
