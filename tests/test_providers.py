import io
from pathlib import Path

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
        self.stdout = io.StringIO('{"type":"done"}\n')

    def wait(self):
        return 0


class OpenStringIO(io.StringIO):
    def close(self):
        return


def test_codex_prompt_uses_stdin_and_writes_log(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["process"] = FakeProcess(command, **kwargs)
        return captured["process"]

    monkeypatch.setattr("medai.providers.subprocess.Popen", fake_popen)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do the work", encoding="utf-8")
    log = tmp_path / "agent.jsonl"

    run_agent(
        provider="codex",
        prompt_path=prompt,
        working_dir=tmp_path,
        log_path=log,
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
    assert '"type":"done"' in log.read_text(encoding="utf-8")


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
