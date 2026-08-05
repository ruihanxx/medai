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
AUTODL_INSTANCES_SCRIPT = ROOT / "scripts" / "autodl_pro_instances.py"
COMPUTATION_PROVIDER_SSH_SCRIPT = (
    ROOT
    / "templates"
    / "skills"
    / "computation_provider"
    / "scripts"
    / "ssh.py"
)


def fake_ssh_environment(tmp_path: Path, probe_exit: int) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "ssh-commands.log"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
if [[ -n "${COMPUTATION_PROVIDER_SSH_PASSWORD:-}" ]]; then
    exit 97
fi
printf 'ssh %s\\n' "$*" >> "$MEDAI_TEST_SSH_COMMAND_LOG"
if [[ "${!#}" == "true" ]]; then
    exit "$MEDAI_TEST_SSH_PROBE_EXIT"
fi
exit 0
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    sshpass = fake_bin / "sshpass"
    sshpass.write_text(
        """#!/usr/bin/env bash
if [[ -n "${COMPUTATION_PROVIDER_SSH_PASSWORD:-}" ]]; then
    exit 97
fi
if [[ -n "${SSHPASS:-}" ]]; then
    password_state=set
else
    password_state=missing
fi
printf 'sshpass %s password=%s\\n' "$*" "$password_state" >> "$MEDAI_TEST_SSH_COMMAND_LOG"
exit 0
""",
        encoding="utf-8",
    )
    sshpass.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "MEDAI_TEST_SSH_COMMAND_LOG": str(command_log),
        "MEDAI_TEST_SSH_PROBE_EXIT": str(probe_exit),
    }
    return environment, command_log


@contextmanager
def autodl_api(
    responses: dict[tuple[str, str], dict[str, object] | list[dict[str, object]]],
):
    requests: list[tuple[str, str, str]] = []
    response_counts: dict[tuple[str, str], int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._respond()

        def do_POST(self):
            self._respond()

        def _respond(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests.append((self.command, self.path, body))
            key = (self.command, self.path.split("?", 1)[0])
            response = responses[key]
            if isinstance(response, list):
                index = response_counts.get(key, 0)
                payload = response[index]
                response_counts[key] = index + 1
            else:
                payload = response
            expected_authorization = payload.get("_expected_authorization")
            if (
                expected_authorization is not None
                and self.headers.get("Authorization") != expected_authorization
            ):
                payload = {
                    "code": "AuthenticationFailed",
                    "msg": "unexpected Authorization header",
                }
            else:
                payload = {
                    name: value
                    for name, value in payload.items()
                    if name != "_expected_authorization"
                }
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


def test_autodl_create_strips_outer_quotes_from_token(tmp_path: Path):
    instance_uuid = "pro-quoted-token"
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "_expected_authorization": "test-token",
                "code": "Success",
                "data": instance_uuid,
            },
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "Success",
                "data": "running",
            },
        }
    ) as (base_url, _):
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
                "AUTODL_TOKEN": '"test-token"',
                "AUTODL_IMAGE_UUID": "base-image-test",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode == 0, completed.stderr


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


def test_autodl_create_tries_one_stronger_gpu_after_no_inventory(tmp_path: Path):
    instance_uuid = "pro-fallback-instance"
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): [
                {"code": "ResourceNotEnough", "msg": "库存不足"},
                {"code": "Success", "data": instance_uuid},
            ],
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "Success",
                "data": "running",
            },
        }
    ) as (base_url, requests):
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "create",
                "--gpu-spec",
                "v-32g-p",
                "--fallback-gpu-spec",
                "v-48g",
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

    assert completed.returncode == 0, completed.stderr
    state = json.loads((tmp_path / "instance.json").read_text(encoding="utf-8"))
    assert state["provider_state"]["gpu_spec_uuid"] == "v-48g"
    assert [json.loads(body)["gpu_spec_uuid"] for _, _, body in requests[:2]] == [
        "v-32g-p",
        "v-48g",
    ]


def test_autodl_pro_instances_lists_from_local_dotenv(tmp_path: Path):
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
            [
                sys.executable,
                str(AUTODL_INSTANCES_SCRIPT),
                "--env-file",
                str(env_file),
                "list",
            ],
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


def test_autodl_pro_instances_operates_on_explicit_uuid(tmp_path: Path):
    instance_uuid = "pro-test"
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/power_on"): {"code": "Success"},
            ("POST", "/api/v1/dev/instance/pro/power_off"): {"code": "Success"},
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "Success",
                "data": "shutdown",
            },
            ("POST", "/api/v1/dev/instance/pro/release"): {"code": "Success"},
        }
    ) as (base_url, requests):
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"AUTODL_TOKEN=test-token\nAUTODL_API_BASE_URL={base_url}\n",
            encoding="utf-8",
        )
        for command in ("power-on", "power-off", "release"):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(AUTODL_INSTANCES_SCRIPT),
                    "--env-file",
                    str(env_file),
                    command,
                    instance_uuid,
                ],
                capture_output=True,
                text=True,
            )
            assert completed.returncode == 0

    assert [(method, path) for method, path, _ in requests] == [
        ("POST", "/api/v1/dev/instance/pro/power_on"),
        ("POST", "/api/v1/dev/instance/pro/power_off"),
        ("GET", f"/api/v1/dev/instance/pro/status?instance_uuid={instance_uuid}"),
        ("POST", "/api/v1/dev/instance/pro/release"),
    ]
    assert json.loads(requests[0][2])["instance_uuid"] == instance_uuid
    assert json.loads(requests[1][2])["instance_uuid"] == instance_uuid
    assert json.loads(requests[3][2])["instance_uuid"] == instance_uuid


def test_computation_provider_prefers_configured_ssh_identity(tmp_path: Path):
    environment, command_log = fake_ssh_environment(tmp_path, probe_exit=0)
    identity = tmp_path / "id_remote"
    identity.write_text("test identity", encoding="utf-8")
    environment.update(
        {
            "COMPUTATION_PROVIDER_SSH_IDENTITY_FILE": str(identity),
            "COMPUTATION_PROVIDER_SSH_PASSWORD": "unused-fallback-password",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(COMPUTATION_PROVIDER_SSH_SCRIPT),
            "--host",
            "remote.example",
            "--port",
            "2200",
            "--user",
            "root",
            "exec",
            "--",
            "echo",
            "ready",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert all("sshpass" not in command for command in commands)
    assert all(f"-i {identity}" in command for command in commands)
    assert commands[0].endswith("root@remote.example true")
    assert commands[1].endswith("root@remote.example echo ready")


def test_autodl_falls_back_to_sshpass_after_key_probe_failure(tmp_path: Path):
    environment, command_log = fake_ssh_environment(tmp_path, probe_exit=255)
    instance_uuid = "pro-ssh-fallback"
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": instance_uuid},
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/snapshot"): {
                "code": "Success",
                "data": {
                    "proxy_host": "remote.example",
                    "ssh_port": 2200,
                    "root_password": "fallback-password",
                },
            }
        }
    ) as (base_url, _):
        environment.update(
            {
                "AUTODL_TOKEN": "test-token",
                "AUTODL_API_BASE_URL": base_url,
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "exec",
                "--state",
                str(state_path),
                "--",
                "echo",
                "ready",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    assert completed.returncode == 0, completed.stderr
    assert "fallback-password" not in completed.stdout + completed.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert commands[0].startswith("ssh ")
    assert commands[0].endswith("root@remote.example true")
    assert commands[1].startswith("sshpass -e ssh ")
    assert commands[1].endswith("root@remote.example echo ready password=set")
