import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUTODL_SCRIPT = (
    ROOT / "templates" / "skills" / "computation_provider" / "scripts" / "autodl.py"
)
AUTODL_LIST_SCRIPT = ROOT / "scripts" / "list_autodl_pro_instances.py"


@contextmanager
def autodl_api(responses: dict[tuple[str, str], dict[str, object]]):
    requests: list[tuple[str, str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._respond()

        def do_POST(self):
            self._respond()

        def _respond(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests.append((self.command, self.path, body))
            payload = responses[(self.command, self.path.split("?", 1)[0])]
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_autodl_skill_help_does_not_call_api():
    completed = subprocess.run(
        [
            sys.executable,
            str(
                AUTODL_SCRIPT
            ),
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "create" in completed.stdout
    assert "release" in completed.stdout
    create_help = subprocess.run(
        [
            sys.executable,
            str(
                AUTODL_SCRIPT
            ),
            "create",
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert create_help.returncode == 0
    assert "--image-uuid" in create_help.stdout


def test_autodl_skill_rejects_gpu_outside_the_pro_pool_before_api_access(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            str(
                AUTODL_SCRIPT
            ),
            "create",
            "--gpu-spec",
            "not-in-pro-pool",
            "--state",
            str(tmp_path / "instance.json"),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "test-token",
            "AUTODL_IMAGE_UUID": "base-image-l2t43iu6uk",
        },
    )
    assert completed.returncode != 0
    assert "Unsupported AutoDL Pro GPU specification" in completed.stderr


def test_autodl_create_uses_query_status_and_retains_state_after_poll_failure(
    tmp_path: Path,
):
    instance_uuid = "pro-test-instance"
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": instance_uuid,
            },
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "RequestParameterIsWrong",
                "msg": "request parameters are wrong",
            },
        }
    ) as (base_url, requests):
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "create",
                "--gpu-spec",
                "v-48g-350w",
                "--state",
                str(tmp_path / "instance.json"),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_IMAGE_UUID": "base-image-test",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode != 0
    state = json.loads((tmp_path / "instance.json").read_text(encoding="utf-8"))
    assert state["provider_state"]["instance_uuid"] == instance_uuid
    assert [(method, path) for method, path, _ in requests] == [
        ("POST", "/api/v1/dev/instance/pro/create"),
        ("GET", f"/api/v1/dev/instance/pro/status?instance_uuid={instance_uuid}"),
    ]
    assert json.loads(requests[0][2])["gpu_spec_uuid"] == "v-48g-350w"
    assert requests[1][2] == ""


def test_list_autodl_pro_instances_reads_local_dotenv(tmp_path: Path):
    expected = {
        "code": "Success",
        "data": {"list": [{"uuid": "pro-test", "status": "shutdown"}]},
    }
    with autodl_api(
        {("POST", "/api/v1/dev/instance/pro/list"): expected}
    ) as (base_url, requests):
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"AUTODL_TOKEN=test-token\nAUTODL_API_BASE_URL={base_url}\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(AUTODL_LIST_SCRIPT), "--env-file", str(env_file)],
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == expected
    assert requests == [
        (
            "POST",
            "/api/v1/dev/instance/pro/list",
            '{"page_index": 1, "page_size": 100}',
        )
    ]
