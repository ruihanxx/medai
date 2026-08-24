import hashlib
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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


def fake_cloud_ssh_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "cloud-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "cloud-ssh-commands.log"
    materialized = tmp_path / "materialized"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="${!#}"
if [[ "$command" == "true" ]]; then
    exit 0
fi
printf 'ssh %s\n' "$command" >> "$MEDAI_TEST_SSH_COMMAND_LOG"
if [[ "$command" == *"df -PB1"* ]]; then
    printf 'Filesystem 1-blocks Used Available Capacity Mounted\n/dev/test 100000 0 100000 0%% /root/autodl-tmp\n'
elif [[ "$command" == *"mv --"* ]]; then
    touch "$MEDAI_TEST_MATERIALIZED"
elif [[ "$command" == *"medai-inventory"*"/root/autodl-tmp/medai/mimic-iv"* ]]; then
    if [[ -f "$MEDAI_TEST_MATERIALIZED" ]]; then printf '2 30\n'; else printf 'missing\n'; fi
elif [[ "$command" == *"medai-inventory"*"/root/autodl-tmp/mimic-iv"* ]]; then
    printf '2 30\n'
fi
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "MEDAI_TEST_SSH_COMMAND_LOG": str(command_log),
        "MEDAI_TEST_MATERIALIZED": str(materialized),
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
            expected_panel_token = payload.get("_expected_panel_token")
            authorization_must_be_absent = payload.get(
                "_expected_authorization_absent", False
            )
            if expected_panel_token is not None and self.headers.get(
                "AutodlAutoPanelToken"
            ) != expected_panel_token:
                payload = {
                    "code": "AuthenticationFailed",
                    "msg": "unexpected AutoPanel instance token header",
                }
            elif authorization_must_be_absent and self.headers.get("Authorization") is not None:
                payload = {
                    "code": "AuthenticationFailed",
                    "msg": "unexpected Authorization header",
                }
            elif (
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
                    if name
                    not in {
                        "_expected_authorization",
                        "_expected_authorization_absent",
                        "_expected_panel_token",
                    }
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
    assert "power-on" in completed.stdout
    assert "power-off" in completed.stdout
    assert "reconcile" in completed.stdout
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
    assert "fallback_gpu_spec_uuid" not in state["provider_state"]
    assert [json.loads(body)["gpu_spec_uuid"] for _, _, body in requests[:2]] == [
        "v-32g-p",
        "v-48g",
    ]


def test_autodl_create_records_unused_resume_fallback(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": "primary-instance",
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
                "v-32g-p",
                "--fallback-gpu-spec",
                "v-48g",
                "--state",
                str(state_path),
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
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider_state"]["fallback_gpu_spec_uuid"] == "v-48g"


def test_autodl_create_archives_released_instance_on_resume(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": True,
                "released_at_unix": 123,
                "provider_state": {
                    "instance_uuid": "old-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "old-image",
                    "cloud_drive": {"status": "failed", "dataset": "mimic-iv"},
                },
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": "replacement-instance",
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
                "v-48g",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_IMAGE_UUID": "new-image",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode == 0, completed.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["released"] is False
    assert state["provider_state"]["instance_uuid"] == "replacement-instance"
    assert state["provider_state"]["instance_history"] == [
        {
            "instance_uuid": "old-instance",
            "gpu_spec_uuid": "v-32g-p",
            "gpu_count": 1,
            "image_uuid": "old-image",
            "cloud_drive": {"status": "failed", "dataset": "mimic-iv"},
            "released_at_unix": 123,
        }
    ]


def test_autodl_create_allows_only_one_replacement_per_manifest_resume(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    state_path.parent.mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"resume_count": 3}), encoding="utf-8"
    )
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": True,
                "released_at_unix": 123,
                "provider_state": {
                    "instance_uuid": "already-replaced",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "image",
                    "created_for_resume_count": 3,
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(AUTODL_SCRIPT),
            "create",
            "--gpu-spec",
            "v-32g-p",
            "--state",
            str(state_path),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "token",
            "AUTODL_IMAGE_UUID": "image",
            "AUTODL_API_BASE_URL": "http://127.0.0.1:1",
        },
    )

    assert completed.returncode != 0
    assert "already created for this manual resume" in completed.stderr


def test_autodl_reconcile_replaces_released_instance_from_recorded_spec(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": True,
                "released_at_unix": 123,
                "provider_state": {
                    "instance_uuid": "released-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 2,
                    "image_uuid": "recorded-image",
                },
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": "replacement-instance",
            },
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
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["replaced"] is True
    create_body = json.loads(
        next(
            body
            for method, path, body in requests
            if method == "POST" and path == "/api/v1/dev/instance/pro/create"
        )
    )
    assert create_body["gpu_spec_uuid"] == "v-32g-p"
    assert create_body["req_gpu_amount"] == 2
    assert create_body["image_uuid"] == "recorded-image"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider_state"]["instance_history"][0]["instance_uuid"] == (
        "released-instance"
    )


def test_autodl_reconcile_powers_on_and_reuses_connectable_instance(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "sleeping-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "fallback_gpu_spec_uuid": "v-48g",
                    "gpu_count": 1,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )
    environment, _ = fake_ssh_environment(tmp_path, probe_exit=0)
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): [
                {"code": "Success", "data": "shutdown"},
                {"code": "Success", "data": "running"},
            ],
            ("POST", "/api/v1/dev/instance/pro/power_on"): {"code": "Success"},
            ("GET", "/api/v1/dev/instance/pro/snapshot"): {
                "code": "Success",
                "data": {"proxy_host": "remote.example", "ssh_port": 2200},
            },
        }
    ) as (base_url, requests):
        environment.update(
            {"AUTODL_TOKEN": "test-token", "AUTODL_API_BASE_URL": base_url}
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["replaced"] is False
    assert [(method, path.split("?", 1)[0]) for method, path, _ in requests] == [
        ("GET", "/api/v1/dev/instance/pro/status"),
        ("POST", "/api/v1/dev/instance/pro/power_on"),
        ("GET", "/api/v1/dev/instance/pro/status"),
        ("GET", "/api/v1/dev/instance/pro/snapshot"),
    ]


def test_autodl_reconcile_releases_unconnectable_instance_before_replacement(
    tmp_path: Path,
):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "broken-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "fallback_gpu_spec_uuid": "v-48g",
                    "gpu_count": 2,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )
    environment, _ = fake_ssh_environment(tmp_path, probe_exit=255)
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): [
                {"code": "Success", "data": "running"},
                {"code": "Success", "data": "running"},
                {"code": "Success", "data": "shutdown"},
                {"code": "Success", "data": "running"},
            ],
            ("GET", "/api/v1/dev/instance/pro/snapshot"): {
                "code": "Success",
                "data": {"proxy_host": "remote.example", "ssh_port": 2200},
            },
            ("POST", "/api/v1/dev/instance/pro/power_off"): {"code": "Success"},
            ("POST", "/api/v1/dev/instance/pro/release"): {"code": "Success"},
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": "replacement-instance",
            },
        }
    ) as (base_url, requests):
        environment.update(
            {"AUTODL_TOKEN": "test-token", "AUTODL_API_BASE_URL": base_url}
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["replaced"] is True
    request_paths = [(method, path.split("?", 1)[0]) for method, path, _ in requests]
    assert request_paths.index(("POST", "/api/v1/dev/instance/pro/release")) < request_paths.index(
        ("POST", "/api/v1/dev/instance/pro/create")
    )
    create_body = next(
        json.loads(body)
        for method, path, body in requests
        if method == "POST" and path == "/api/v1/dev/instance/pro/create"
    )
    assert create_body["gpu_spec_uuid"] == "v-32g-p"
    assert create_body["req_gpu_amount"] == 2
    assert create_body["image_uuid"] == "image"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider_state"]["instance_uuid"] == "replacement-instance"
    assert state["provider_state"]["fallback_gpu_spec_uuid"] == "v-48g"


def test_autodl_reconcile_replaces_provider_confirmed_missing_instance(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "missing-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): [
                {"code": "NotFound", "msg": "实例不存在"},
                {"code": "Success", "data": "running"},
            ],
            ("POST", "/api/v1/dev/instance/pro/create"): {
                "code": "Success",
                "data": "replacement-instance",
            },
        }
    ) as (base_url, requests):
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["replaced"] is True
    assert not [path for method, path, _ in requests if method == "POST" and "release" in path]


def test_autodl_reconcile_does_not_replace_on_uncertain_provider_error(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "uncertain-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "ServiceUnavailable",
                "msg": "temporary API timeout",
            },
        }
    ) as (base_url, requests):
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode != 0
    assert [(method, path.split("?", 1)[0]) for method, path, _ in requests] == [
        ("GET", "/api/v1/dev/instance/pro/status")
    ]
    assert json.loads(state_path.read_text(encoding="utf-8"))["released"] is False


def test_autodl_reconcile_does_not_create_when_old_release_fails(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "broken-instance",
                    "gpu_spec_uuid": "v-32g-p",
                    "gpu_count": 1,
                    "image_uuid": "image",
                },
            }
        ),
        encoding="utf-8",
    )
    environment, _ = fake_ssh_environment(tmp_path, probe_exit=255)
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): [
                {"code": "Success", "data": "running"},
                {"code": "Success", "data": "running"},
                {"code": "Success", "data": "shutdown"},
            ],
            ("GET", "/api/v1/dev/instance/pro/snapshot"): {
                "code": "Success",
                "data": {"proxy_host": "remote.example", "ssh_port": 2200},
            },
            ("POST", "/api/v1/dev/instance/pro/power_off"): {"code": "Success"},
            ("POST", "/api/v1/dev/instance/pro/release"): {
                "code": "ReleaseFailed",
                "msg": "still attached",
            },
        }
    ) as (base_url, requests):
        environment.update(
            {"AUTODL_TOKEN": "test-token", "AUTODL_API_BASE_URL": base_url}
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "reconcile",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    assert completed.returncode != 0
    request_paths = [(method, path.split("?", 1)[0]) for method, path, _ in requests]
    assert ("POST", "/api/v1/dev/instance/pro/release") in request_paths
    assert ("POST", "/api/v1/dev/instance/pro/create") not in request_paths
    assert json.loads(state_path.read_text(encoding="utf-8"))["released"] is False


@pytest.mark.parametrize("state_text", ["{", "[]"])
def test_autodl_reconcile_rejects_corrupt_state_before_api(
    tmp_path: Path,
    state_text: str,
):
    state_path = tmp_path / "instance.json"
    state_path.write_text(state_text, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(AUTODL_SCRIPT),
            "reconcile",
            "--state",
            str(state_path),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "test-token",
            "AUTODL_API_BASE_URL": "http://127.0.0.1:1",
        },
    )

    assert completed.returncode != 0
    assert "state" in completed.stderr.casefold()


def test_autodl_reconcile_requires_recreation_fields_before_api_access(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": True,
                "provider_state": {"instance_uuid": "old-instance"},
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(AUTODL_SCRIPT),
            "reconcile",
            "--state",
            str(state_path),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "test-token",
            "AUTODL_API_BASE_URL": "http://127.0.0.1:1",
        },
    )

    assert completed.returncode != 0
    assert "missing: gpu_spec_uuid, gpu_count, image_uuid" in completed.stderr


def test_autodl_release_refuses_before_pipeline_completion(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    state_path.parent.mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "status": "running",
                "stages": {"report_agents": {"status": "completed"}},
            }
        ),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "instance"},
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(AUTODL_SCRIPT),
            "release",
            "--state",
            str(state_path),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AUTODL_TOKEN": "test-token",
            "AUTODL_API_BASE_URL": "http://127.0.0.1:1",
        },
    )

    assert completed.returncode != 0
    assert "before report and pipeline completion" in completed.stderr


def test_autodl_release_keeps_autoresearch_lifecycle_compatible(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    state_path.parent.mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "inputs": {"workflow": "autoresearch"},
                "stages": {"report_agents": {"status": "failed"}},
            }
        ),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "instance"},
            }
        ),
        encoding="utf-8",
    )
    with autodl_api(
        {
            ("GET", "/api/v1/dev/instance/pro/status"): {
                "code": "Success",
                "data": "shutdown",
            },
            ("POST", "/api/v1/dev/instance/pro/release"): {"code": "Success"},
        }
    ) as (base_url, _):
        completed = subprocess.run(
            [
                sys.executable,
                str(AUTODL_SCRIPT),
                "release",
                "--state",
                str(state_path),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AUTODL_TOKEN": "test-token",
                "AUTODL_API_BASE_URL": base_url,
            },
        )

    assert completed.returncode == 0, completed.stderr


def _cloud_task(task_id: str, name: str, size: int, status: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_type": 2,
        "status": status,
        "fsid": "ali-fs",
        "drive_id": "backup-drive",
        "dst_path": "/root/autodl-tmp/mimic-iv",
        "file_name": name,
        "file_size": size,
    }


def _task_response(
    *,
    pre: list[dict[str, object]] | None = None,
    doing: list[dict[str, object]] | None = None,
    done: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    pre = pre or []
    doing = doing or []
    done = done or []
    return {
        "code": "success",
        "data": {
            "task_pre": pre,
            "task_doing": doing,
            "task_done": done,
            "task_success": sum(item.get("status") == "success" for item in done),
            "task_total": len(pre) + len(doing) + len(done),
        },
    }


def _cloud_api_responses(task_responses: list[dict[str, object]] | None = None):
    directory_pages = [
        {
            "code": "success",
            "data": {
                "list": {
                    "FsType": "AutoDL_AliPan",
                    "List": [
                        {"name": "medai", "file_id": "dir-medai", "is_dir": True}
                    ],
                },
                "next_marker": "",
            },
        },
        {
            "code": "success",
            "data": {
                "list": {
                    "FsType": "AutoDL_AliPan",
                    "List": [
                        {
                            "name": "mimic-iv",
                            "file_id": "dir-dataset",
                            "is_dir": True,
                            "size": 0,
                        }
                    ],
                },
                "next_marker": "",
            },
        },
        {
            "code": "success",
            "data": {
                "list": {
                    "FsType": "AutoDL_AliPan",
                    "List": [
                        {
                            "name": "one.csv",
                            "file_id": "f1",
                            "is_dir": False,
                            "size": 10,
                        },
                        {"name": "nested", "file_id": "dir-nested", "is_dir": True},
                    ],
                },
                "next_marker": "",
            },
        },
        {
            "code": "success",
            "data": {
                "list": {
                    "FsType": "AutoDL_AliPan",
                    "List": [
                        {
                            "name": "two.csv",
                            "file_id": "f2",
                            "is_dir": False,
                            "size": 20,
                        }
                    ],
                },
                "next_marker": "",
            },
        },
    ]
    return {
        ("GET", "/api/v1/dev/instance/pro/snapshot"): {
            "code": "Success",
            "data": {
                "proxy_host": "remote.example",
                "ssh_port": 2200,
                "jupyter_domain": "__BASE_URL__",
                "jupyter_token": "panel-instance-token",
            },
        },
        ("POST", "/autopanel/v1/sign_in"): {
            "code": "success",
            "data": "panel-session",
            "_expected_panel_token": "panel-instance-token",
            "_expected_authorization_absent": True,
        },
        ("GET", "/autopanel/v1/netdisk/list"): {
            "code": "success",
            "data": [
                {
                    "type": "AutoDL_AliPan",
                    "fs_id": "ali-fs",
                    "user_info": {"default_drive_id": "backup-drive"},
                }
            ],
        },
        ("GET", "/autopanel/v1/netdisk/file"): directory_pages * 2,
        ("POST", "/autopanel/v1/netdisk/download"): {
            "code": "success",
            "data": None,
        },
        ("GET", "/autopanel/v1/netdisk/task"): task_responses
        or [
            _task_response(),
            _task_response(
                pre=[
                    _cloud_task("task-1", "one.csv", 10, "pre"),
                    _cloud_task("task-2", "two.csv", 20, "pre"),
                ]
            ),
            _task_response(
                done=[
                    _cloud_task("task-1", "one.csv", 10, "success"),
                    _cloud_task("task-2", "two.csv", 20, "success"),
                ]
            ),
        ],
    }


def _run_cloud_pull(
    *, state_path: Path, base_url: str, environment: dict[str, str], timeout: str = "30"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(AUTODL_SCRIPT),
            "cloud-pull",
            "--state",
            str(state_path),
            "--dataset",
            "mimic-iv",
        ],
        capture_output=True,
        text=True,
        env={
            **environment,
            "AUTODL_TOKEN": "api-secret",
            "AUTODL_API_BASE_URL": base_url,
            "AUTODL_AUTOPANEL_PASSWORD": "panel-secret",
            "AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS": timeout,
        },
    )


def test_autodl_cloud_pull_materializes_and_records_only_nonsecret_state(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "cloud-instance"},
            }
        ),
        encoding="utf-8",
    )
    environment, command_log = fake_cloud_ssh_environment(tmp_path)
    responses = _cloud_api_responses()
    with autodl_api(responses) as (base_url, requests):
        responses[("GET", "/api/v1/dev/instance/pro/snapshot")]["data"][
            "jupyter_domain"
        ] = base_url
        completed = _run_cloud_pull(
            state_path=state_path, base_url=base_url, environment=environment
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "/root/autodl-tmp/medai/mimic-iv"
    state_text = state_path.read_text(encoding="utf-8")
    assert "panel-secret" not in state_text + completed.stdout + completed.stderr
    plain_hash = hashlib.sha1(b"panel-secret").hexdigest()
    salted_hash = hashlib.sha1(b"autodlpanel-secretAutoDL").hexdigest()
    assert plain_hash not in state_text
    assert salted_hash not in state_text
    cloud = json.loads(state_text)["provider_state"]["cloud_drive"]
    assert cloud["status"] == "completed"
    assert cloud["remote_file_count"] == cloud["local_file_count"] == 2
    assert cloud["remote_total_bytes"] == cloud["local_total_bytes"] == 30
    assert cloud["target_path"] == "/root/autodl-tmp/medai/mimic-iv"
    commands = command_log.read_text(encoding="utf-8")
    assert "rm -rf" not in commands
    assert "chmod -R a-w" in commands
    sign_in = next(body for method, path, body in requests if path == "/autopanel/v1/sign_in")
    assert json.loads(sign_in)["password"] == salted_hash
    file_requests = [path for _, path, _ in requests if "/netdisk/file?" in path]
    assert file_requests
    assert all("driver_id=backup-drive" in path for path in file_requests)
    download = next(body for _, path, body in requests if path == "/autopanel/v1/netdisk/download")
    download_body = json.loads(download)
    assert download_body["drive_id"] == "backup-drive"
    assert download_body["src_path"] == "/medai/mimic-iv/"
    assert download_body["file_size"] == 0


def test_autodl_cloud_pull_timeout_reuses_active_task(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "cloud-instance"},
            }
        ),
        encoding="utf-8",
    )
    environment, _ = fake_cloud_ssh_environment(tmp_path)
    task_responses = [
        _task_response(),
        _task_response(
            pre=[
                _cloud_task("task-1", "one.csv", 10, "pre"),
                _cloud_task("task-2", "two.csv", 20, "pre"),
            ]
        ),
        _task_response(
            pre=[
                _cloud_task("task-1", "one.csv", 10, "pre"),
                _cloud_task("task-2", "two.csv", 20, "pre"),
            ]
        ),
        _task_response(
            done=[
                _cloud_task("task-1", "one.csv", 10, "success"),
                _cloud_task("task-2", "two.csv", 20, "success"),
            ]
        ),
    ]
    responses = _cloud_api_responses(task_responses)
    with autodl_api(responses) as (base_url, requests):
        responses[("GET", "/api/v1/dev/instance/pro/snapshot")]["data"][
            "jupyter_domain"
        ] = base_url
        timed_out = _run_cloud_pull(
            state_path=state_path,
            base_url=base_url,
            environment=environment,
            timeout="1",
        )
        resumed = _run_cloud_pull(
            state_path=state_path, base_url=base_url, environment=environment
        )

    assert timed_out.returncode != 0
    assert "timed out" in timed_out.stderr
    assert resumed.returncode == 0, resumed.stderr
    downloads = [path for method, path, _ in requests if path == "/autopanel/v1/netdisk/download"]
    assert downloads == ["/autopanel/v1/netdisk/download"]


def test_autodl_cloud_pull_fails_fast_on_ambiguous_aliyun_binding(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {"instance_uuid": "cloud-instance"},
            }
        ),
        encoding="utf-8",
    )
    environment, _ = fake_cloud_ssh_environment(tmp_path)
    responses = _cloud_api_responses()
    responses[("GET", "/autopanel/v1/netdisk/list")] = {
        "code": "success",
        "data": [
            {
                "type": "AutoDL_AliPan",
                "fs_id": "one",
                "user_info": {"default_drive_id": "drive-one"},
            },
            {
                "type": "AutoDL_AliPan",
                "fs_id": "two",
                "user_info": {"default_drive_id": "drive-two"},
            },
        ],
    }
    with autodl_api(responses) as (base_url, _):
        responses[("GET", "/api/v1/dev/instance/pro/snapshot")]["data"][
            "jupyter_domain"
        ] = base_url
        completed = _run_cloud_pull(
            state_path=state_path, base_url=base_url, environment=environment
        )

    assert completed.returncode != 0
    assert "exactly one explicit Aliyun binding" in completed.stderr
    assert "panel-secret" not in completed.stderr


def test_autodl_cloud_pull_failed_retry_deletes_only_recorded_exact_paths(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": "cloud-instance",
                    "cloud_drive": {
                        "provider": "aliyun",
                        "dataset": "mimic-iv",
                        "source_path": "medai/mimic-iv",
                        "staging_path": "/root/autodl-tmp/mimic-iv",
                        "target_path": "/root/autodl-tmp/medai/mimic-iv",
                        "owned_paths": True,
                        "status": "failed",
                        "remote_file_count": 2,
                        "remote_total_bytes": 30,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    environment, command_log = fake_cloud_ssh_environment(tmp_path)
    responses = _cloud_api_responses()
    with autodl_api(responses) as (base_url, _):
        responses[("GET", "/api/v1/dev/instance/pro/snapshot")]["data"][
            "jupyter_domain"
        ] = base_url
        completed = _run_cloud_pull(
            state_path=state_path, base_url=base_url, environment=environment
        )

    assert completed.returncode == 0, completed.stderr
    cleanup = next(
        line
        for line in command_log.read_text(encoding="utf-8").splitlines()
        if "rm -rf" in line
    )
    assert "/root/autodl-tmp/mimic-iv" in cleanup
    assert "/root/autodl-tmp/medai/mimic-iv" in cleanup
    assert "*" not in cleanup


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
