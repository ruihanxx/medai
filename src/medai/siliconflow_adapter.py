from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values

from medai.artifacts import write_json

ADAPTER_TOKEN_ENV = "MEDAI_CODEX_SILICONFLOW_ADAPTER_TOKEN"


@dataclass(frozen=True)
class SiliconFlowConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    context_window: int = 131072
    timeout_seconds: int = 1200

    @classmethod
    def from_dotenv(cls, path: Path) -> "SiliconFlowConfig":
        if not path.is_file():
            raise FileNotFoundError(f"SiliconFlow config does not exist: {path}")
        values = {str(key): str(value) for key, value in dotenv_values(path).items() if value}
        api_key = values.get("SILICONFLOW_API_KEY", "").strip()
        if not api_key:
            raise ValueError(f"SILICONFLOW_API_KEY is missing from {path}")
        base_url = values.get("SILICONFLOW_BASE_URL", cls.base_url).strip().rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SILICONFLOW_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("SILICONFLOW_BASE_URL must use HTTPS unless it is local")
        model = values.get("CODEX_CLI_SILICONFLOW_MODEL", cls.model).strip()
        context_window = int(
            values.get("CODEX_CLI_SILICONFLOW_CONTEXT_WINDOW", str(cls.context_window))
        )
        timeout_seconds = int(values.get("CODEX_CLI_TIMEOUT_SECONDS", str(cls.timeout_seconds)))
        if not model or context_window <= 0 or timeout_seconds <= 0:
            raise ValueError("SiliconFlow model, context window, and timeout must be positive")
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            context_window=context_window,
            timeout_seconds=timeout_seconds,
        )


class SiliconFlowAdapter:
    def __init__(self, settings: SiliconFlowConfig, *, artifact_dir: Path):
        self.settings = settings
        self.artifact_dir = artifact_dir
        self.token = secrets.token_urlsafe(32)
        self.base_url = ""
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.request_count = 0

    def __enter__(self) -> "SiliconFlowAdapter":
        adapter = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                adapter._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                adapter._handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def codex_args(self) -> list[str]:
        if not self.base_url:
            raise RuntimeError("SiliconFlow adapter has not started")
        return [
            "--ignore-user-config",
            "--ephemeral",
            "-c",
            'model_provider="siliconflow"',
            "-c",
            'model_providers.siliconflow.name="SiliconFlow via medai adapter"',
            "-c",
            f"model_providers.siliconflow.base_url={json.dumps(self.base_url)}",
            "-c",
            f"model_providers.siliconflow.env_key={json.dumps(ADAPTER_TOKEN_ENV)}",
            "-c",
            'model_providers.siliconflow.wire_api="responses"',
            "-c",
            "model_providers.siliconflow.requires_openai_auth=false",
            "-c",
            "model_providers.siliconflow.supports_websockets=false",
            "-c",
            f"model_context_window={self.settings.context_window}",
            "-c",
            'web_search="disabled"',
            "--disable",
            "multi_agent",
            "--disable",
            "apps",
            "--disable",
            "plugins",
            "--model",
            self.settings.model,
        ]

    def child_environment(self, base: Mapping[str, str]) -> dict[str, str]:
        environment = dict(base)
        for key, value in tuple(environment.items()):
            if key == "SILICONFLOW_API_KEY" or value == self.settings.api_key:
                environment.pop(key, None)
        environment[ADAPTER_TOKEN_ENV] = self.token
        return environment

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        supplied = handler.headers.get("Authorization", "")
        return secrets.compare_digest(supplied, f"Bearer {self.token}")

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authorized(handler):
            self._send_json(handler, 401, {"error": {"message": "Invalid adapter token"}})
            return
        if urllib.parse.urlsplit(handler.path).path not in {"/v1/models", "/models"}:
            self._send_json(handler, 404, {"error": {"message": "Unsupported path"}})
            return
        model = {
            "slug": self.settings.model,
            "display_name": self.settings.model,
            "description": "SiliconFlow model through the local medai adapter.",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "Light reasoning"},
                {"effort": "medium", "description": "Balanced reasoning"},
                {"effort": "high", "description": "Deep reasoning"},
            ],
            "shell_type": "shell_command",
            "visibility": "list",
            "supported_in_api": True,
            "priority": 0,
            "context_window": self.settings.context_window,
            "max_context_window": self.settings.context_window,
            "effective_context_window_percent": 95,
            "input_modalities": ["text"],
            "supports_parallel_tool_calls": True,
            "supports_reasoning_summaries": False,
            "supports_search_tool": False,
            "experimental_supported_tools": [],
            "apply_patch_tool_type": "freeform",
            "truncation_policy": {"mode": "tokens", "limit": self.settings.context_window},
            "use_responses_lite": False,
        }
        self._send_json(
            handler,
            200,
            {
                "models": [model],
                "object": "list",
                "data": [
                    {
                        "id": self.settings.model,
                        "object": "model",
                        "created": 0,
                        "owned_by": "siliconflow",
                    }
                ],
            },
        )

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        self.request_count += 1
        log_path = self.artifact_dir / f"siliconflow_adapter_{self.request_count:03d}.json"
        record: dict[str, Any] = {"request_id": self.request_count}
        if not self._authorized(handler):
            self._send_json(handler, 401, {"error": {"message": "Invalid adapter token"}})
            record.update({"status": "failed", "error": "unauthorized"})
            write_json(log_path, record)
            return
        if urllib.parse.urlsplit(handler.path).path not in {"/v1/responses", "/responses"}:
            self._send_json(handler, 404, {"error": {"message": "Unsupported path"}})
            record.update({"status": "failed", "error": "unsupported_path"})
            write_json(log_path, record)
            return

        try:
            length = int(handler.headers.get("Content-Length", "0"))
            payload = json.loads(handler.rfile.read(length).decode("utf-8"))
            chat_payload = responses_to_chat(payload)
            chat_payload["model"] = self.settings.model
            upstream = urllib.request.Request(
                f"{self.settings.base_url}/chat/completions",
                data=json.dumps(chat_payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(
                upstream, timeout=self.settings.timeout_seconds
            ) as response:
                upstream_payload = json.loads(response.read().decode("utf-8"))
            items = chat_to_response_items(upstream_payload)
            self._send_events(
                handler,
                response_id=str(upstream_payload.get("id") or f"resp_{uuid.uuid4().hex}"),
                items=items,
                usage=upstream_payload.get("usage"),
            )
            record.update(
                {
                    "status": "ok",
                    "model": self.settings.model,
                    "message_count": len(chat_payload["messages"]),
                    "tool_count": len(chat_payload.get("tools", [])),
                    "usage": response_usage(upstream_payload.get("usage")),
                }
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._send_json(handler, exc.code, {"error": {"message": detail[-2000:]}})
            record.update({"status": "failed", "error": detail[-2000:]})
        except Exception as exc:
            message = str(exc).replace(self.settings.api_key, "[REDACTED]")
            self._send_json(handler, 500, {"error": {"message": message}})
            record.update({"status": "failed", "error": message})
        finally:
            write_json(log_path, record)

    def _send_events(
        self,
        handler: BaseHTTPRequestHandler,
        *,
        response_id: str,
        items: list[dict[str, Any]],
        usage: Any,
    ) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        for index, item in enumerate(items):
            for event_name in ("response.output_item.added", "response.output_item.done"):
                payload = {
                    "type": event_name,
                    "output_index": index,
                    "item": item,
                }
                handler.wfile.write(
                    f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                )
        completed = {
            "type": "response.completed",
            "response": {
                "id": response_id,
                "object": "response",
                "created_at": int(time.time()),
                "status": "completed",
                "model": self.settings.model,
                "output": items,
                "usage": response_usage(usage),
            },
        }
        handler.wfile.write(
            (
                "event: response.completed\n"
                f"data: {json.dumps(completed, ensure_ascii=False)}\n\n"
            ).encode("utf-8")
        )
        handler.wfile.flush()

    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


def responses_to_chat(payload: dict[str, Any]) -> dict[str, Any]:
    system_parts = []
    if payload.get("instructions"):
        system_parts.append(str(payload["instructions"]))
    raw_input = payload.get("input") or []
    if isinstance(raw_input, str):
        raw_input = [{"type": "message", "role": "user", "content": raw_input}]

    messages: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []
    for item in raw_input:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "function_call":
            pending_calls.append(
                {
                    "id": str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}"),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": json_string(item.get("arguments") or "{}"),
                    },
                }
            )
            continue
        if pending_calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": pending_calls})
            pending_calls = []
        if item_type == "function_call_output":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or ""),
                    "content": str(item.get("output") or ""),
                }
            )
        elif item_type == "message" or "role" in item:
            role = str(item.get("role") or "user")
            content = flatten_content(item.get("content"))
            if role in {"system", "developer"}:
                system_parts.append(content)
            else:
                messages.append(
                    {"role": "assistant" if role == "assistant" else "user", "content": content}
                )
    if pending_calls:
        messages.append({"role": "assistant", "content": None, "tool_calls": pending_calls})
    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
    if not messages:
        messages.append({"role": "user", "content": ""})

    chat_payload: dict[str, Any] = {
        "model": str(payload.get("model") or ""),
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
    }
    tools = []
    for tool in payload.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            function = {
                "name": tool.get("name"),
                "description": tool.get("description") or "",
                "parameters": tool.get("parameters")
                or {"type": "object", "properties": {}},
            }
        if function.get("name"):
            tools.append({"type": "function", "function": function})
    if tools:
        chat_payload["tools"] = tools
        if payload.get("tool_choice") in {"auto", "none", "required"}:
            chat_payload["tool_choice"] = payload["tool_choice"]
    if isinstance(payload.get("max_output_tokens"), int):
        chat_payload["max_tokens"] = payload["max_output_tokens"]
    return chat_payload


def chat_to_response_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("SiliconFlow response contains no completion choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("SiliconFlow completion contains no message")
    items = []
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else {}
        function = function if isinstance(function, dict) else {}
        items.append(
            {
                "id": f"fc_{uuid.uuid4().hex}",
                "type": "function_call",
                "status": "completed",
                "call_id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex}"),
                "name": str(function.get("name") or ""),
                "arguments": json_string(function.get("arguments") or "{}"),
            }
        )
    content = message.get("content")
    if content is not None or not items:
        items.append(
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": str(content or "")}],
            }
        )
    return items


def flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts = []
    for item in content:
        if isinstance(item, dict) and "text" in item:
            parts.append(str(item.get("text") or ""))
        elif isinstance(item, dict) and item.get("type") == "input_image":
            parts.append("[image input omitted]")
        else:
            parts.append(str(item))
    return "\n".join(part for part in parts if part)


def json_string(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def response_usage(usage: Any) -> dict[str, int]:
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
    }
