import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from medai.computation_providers import get_provider_adapter
from medai.config import RunConfig

ROOT = Path(__file__).parents[1]
VASTAI_SCRIPT = (
    ROOT / "templates" / "skills" / "computation_provider" / "scripts" / "vastai.py"
)


def offer(
    offer_id: str,
    *,
    gpu_name: str = "RTX 4090",
    gpu_count: int = 1,
    gpu_ram_mb: int = 24576,
    cpu_ram_mb: int = 65536,
    total_flops: float = 82.6,
    dph_total: float = 1.0,
    reliability: float = 0.995,
) -> dict[str, Any]:
    return {
        "id": offer_id,
        "gpu_name": gpu_name,
        "cpu_arch": "amd64",
        "num_gpus": gpu_count,
        "gpu_ram": gpu_ram_mb,
        "cpu_ram": cpu_ram_mb,
        "total_flops": total_flops,
        "dph_total": dph_total,
        "reliability": reliability,
    }


@contextmanager
def vast_api(routes: dict[tuple[str, str], Any]):
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_DELETE(self):
            self.respond()

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def do_PUT(self):
            self.respond()

        def respond(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            path = self.path.split("?", 1)[0]
            key = (self.command, path)
            requests.append(
                {
                    "method": self.command,
                    "path": path,
                    "body": json.loads(body) if body else None,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            response = routes[key]
            if callable(response):
                response = response(requests)
            status, payload = response if isinstance(response, tuple) else (200, response)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
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


def adapter_environment(base_url: str) -> dict[str, str]:
    return {
        **os.environ,
        "VAST_API_KEY": "vast-secret",
        "VASTAI_IMAGE": "registry.example/medai@sha256:image",
        "VASTAI_API_BASE_URL": base_url,
    }


def cloud_inventory(dataset: str, digest: str = "a" * 64) -> str:
    return json.dumps(
        {
            "version": 1,
            "algorithm": "sha256",
            "dataset": dataset,
            "files": [{"path": "data.csv", "size": 12, "sha256": digest}],
            "file_count": 1,
            "total_bytes": 12,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def vast_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "vastai",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "schema_version": 1,
                    "run_token": "test-run",
                    "label": "medai-test-run",
                    "instance_id": "instance-1",
                    "requested": {
                        "gpu_name": None,
                        "gpu_count": 1,
                        "min_gpu_ram_gb": 24,
                        "min_cpu_ram_gb": 32,
                        "max_dph": 2.0,
                        "min_reliability": 0.99,
                        "disk_gb": 64,
                        "image": "registry.example/medai@sha256:image",
                    },
                    "selected_offer": {
                        "id": "primary",
                        "gpu_name": "RTX 4090",
                        "cpu_arch": "amd64",
                        "gpu_count": 1,
                        "gpu_ram_mb": 24576,
                        "cpu_ram_mb": 65536,
                        "total_flops": 82.6,
                        "dph_total": 1.0,
                        "reliability": 0.995,
                    },
                    "remote_working_dir": "/workspace/medai/test-run/work",
                },
            }
        ),
        encoding="utf-8",
    )


def fake_cloud_ssh_environment(tmp_path: Path, inventory: str) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "cloud-bin"
    fake_bin.mkdir(parents=True)
    command_log = tmp_path / "cloud-commands.log"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="${!#}"
if [[ "$command" == "true" ]]; then
    exit 0
fi
printf '%s\\n' "$command" >> "$MEDAI_TEST_CLOUD_COMMAND_LOG"
if [[ "$command" == *"medai-cloud-inventory"* ]]; then
    printf '%s\\n' "$MEDAI_TEST_CLOUD_INVENTORY"
fi
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    return (
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "MEDAI_TEST_CLOUD_COMMAND_LOG": str(command_log),
            "MEDAI_TEST_CLOUD_INVENTORY": inventory,
        },
        command_log,
    )


def load_vastai_module():
    spec = importlib.util.spec_from_file_location("medai_test_vastai", VASTAI_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_adapter(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VASTAI_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        env=environment,
    )


def test_vastai_metadata_selects_without_persisting_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEDAI_COMPUTATION_PROVIDER", "vastai")
    monkeypatch.setenv("VAST_API_KEY", "vast-secret")
    monkeypatch.setenv("VASTAI_IMAGE", "registry.example/medai@sha256:image")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "run",
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )

    assert config.computation_provider == "vastai"
    assert config.computation_provider_config == {
        "provider": "vastai",
        "drive": None,
        "values": {
            "VASTAI_IMAGE": "registry.example/medai@sha256:image",
            "VASTAI_API_BASE_URL": "https://console.vast.ai",
            "VASTAI_MAX_DPH": "2",
            "VASTAI_DISK_GB": "64",
            "VASTAI_DEFAULT_GPU_COUNT": "1",
            "VASTAI_MIN_GPU_RAM_GB": "24",
            "VASTAI_MIN_CPU_RAM_GB": "32",
            "VASTAI_MIN_RELIABILITY": "0.99",
        },
    }
    assert "vast-secret" not in json.dumps(config.computation_provider_config)
    assert get_provider_adapter("vastai").script == VASTAI_SCRIPT


def test_vastai_search_filters_and_stably_sorts_eligible_offers(tmp_path: Path):
    del tmp_path
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {
                "offers": [
                    offer("slow", dph_total=1.2, reliability=0.99),
                    offer("expensive", dph_total=2.1),
                    offer("cheap-b", dph_total=0.8, reliability=0.995),
                    offer("cheap-a", dph_total=0.8, reliability=0.995),
                    offer("small", gpu_ram_mb=16384),
                ]
            }
        }
    ) as (base_url, requests):
        completed = run_adapter(["search"], adapter_environment(base_url))

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert [item["id"] for item in payload["offers"]] == ["cheap-a", "cheap-b", "slow"]
    assert requests[0]["authorization"] == "Bearer vast-secret"
    assert requests[0]["body"] == {
        "limit": 100,
        "type": "on-demand",
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "cpu_arch": {"in": ["amd64", "x86_64"]},
        "num_gpus": {"gte": 1},
        "gpu_ram": {"gte": 24 * 1024},
        "cpu_ram": {"gte": 32 * 1024},
        "dph_total": {"lte": 2.0},
        "reliability": {"gte": 0.99},
        "disk_space": {"gte": 64},
        "allocated_storage": 64,
        "order": [
            ["dph_total", "asc"],
            ["reliability", "desc"],
            ["id", "asc"],
        ],
    }


def test_vastai_create_records_nonsecret_state_and_requested_container(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    selected = offer("primary")
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [selected]},
            ("PUT", "/api/v0/asks/primary/"): {"success": True, "new_contract": "instance-1"},
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["create", "--state", str(state_path), "--offer-id", "primary"],
            adapter_environment(base_url),
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "instance-1"
    created = next(item for item in requests if item["path"] == "/api/v0/asks/primary/")
    assert created["body"]["disk"] == 64
    assert created["body"]["image"] == "registry.example/medai@sha256:image"
    assert created["body"]["runtype"] == "ssh"
    assert created["body"]["target_state"] == "running"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider"] == "vastai"
    assert state["provider_state"]["instance_id"] == "instance-1"
    assert state["provider_state"]["requested"]["min_gpu_ram_gb"] == 24
    assert "/workspace/medai/" in state["provider_state"]["remote_working_dir"]
    assert "vast-secret" not in state_path.read_text(encoding="utf-8")


def test_vastai_uses_one_fallback_only_after_explicit_primary_no_inventory(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    primary = offer("primary", total_flops=80.0)
    fallback = offer("fallback", gpu_name="RTX 6000 Ada", gpu_ram_mb=49152, total_flops=91.0)
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [primary, fallback]},
            ("PUT", "/api/v0/asks/primary/"): (409, {"msg": "offer is no longer available"}),
            ("GET", "/api/v1/instances/"): {"instances": []},
            ("PUT", "/api/v0/asks/fallback/"): {"success": True, "new_contract": "instance-2"},
            ("GET", "/api/v0/instances/instance-2/"): {"instances": {"actual_status": "running"}},
        }
    ) as (base_url, requests):
        completed = run_adapter(
            [
                "create",
                "--state",
                str(state_path),
                "--offer-id",
                "primary",
                "--fallback-offer-id",
                "fallback",
            ],
            adapter_environment(base_url),
        )

    assert completed.returncode == 0, completed.stderr
    creates = [item["path"] for item in requests if item["method"] == "PUT"]
    assert creates == ["/api/v0/asks/primary/", "/api/v0/asks/fallback/"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider_state"]["instance_id"] == "instance-2"
    assert state["provider_state"]["selected_offer"]["id"] == "fallback"
    assert state["provider_state"]["primary_offer"]["id"] == "primary"


def test_vastai_preserves_uncertain_creation_without_retrying_a_second_offer(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {
                "offers": [offer("primary"), offer("fallback", gpu_ram_mb=49152, total_flops=90)]
            },
            ("PUT", "/api/v0/asks/primary/"): (500, {"msg": "temporary upstream failure"}),
        }
    ) as (base_url, requests):
        completed = run_adapter(
            [
                "create",
                "--state",
                str(state_path),
                "--offer-id",
                "primary",
                "--fallback-offer-id",
                "fallback",
            ],
            adapter_environment(base_url),
        )

    assert completed.returncode != 0
    assert "/api/v0/asks/fallback/" not in [item["path"] for item in requests]
    state_text = state_path.read_text(encoding="utf-8")
    assert json.loads(state_text)["provider_state"]["creation_uncertain"] is True
    assert "vast-secret" not in state_text
    assert "vast-secret" not in completed.stderr


def test_vastai_validate_state_rejects_tampering_without_contacting_api(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    state_path.write_text(
        json.dumps(
            {
                "provider": "vastai",
                "created_by_run": True,
                "released": False,
                "provider_state": {"schema_version": 1},
            }
        ),
        encoding="utf-8",
    )

    completed = run_adapter(
        ["validate-state", "--state", str(state_path)],
        {**os.environ, "VAST_API_KEY": "vast-secret", "VASTAI_IMAGE": "image"},
    )

    assert completed.returncode != 0
    assert "run_token" in completed.stderr


def test_vastai_reconcile_starts_a_stopped_instance_and_reuses_a_healthy_ssh_connection(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, _ = fake_cloud_ssh_environment(tmp_path, cloud_inventory("dataset-a"))
    states = iter(["stopped", "running", "running"])
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: {
                "instances": {"actual_status": next(states), "ssh_host": "host", "ssh_port": 22}
            },
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["reconcile", "--state", str(state_path)],
            {**adapter_environment(base_url), **ssh_environment},
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"instance_id": "instance-1", "replaced": False, "status": "running"}
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [{"state": "running"}]


def test_vastai_release_stops_then_confirms_irreversible_destroy(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "stages": {"report_agents": {"status": "completed"}},
            }
        ),
        encoding="utf-8",
    )
    responses = iter(
        [
            {"instances": {"actual_status": "running"}},
            {"instances": {"actual_status": "stopped"}},
            (404, {"msg": "not found"}),
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: next(responses),
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
            ("DELETE", "/api/v0/instances/instance-1/"): {"success": True},
        }
    ) as (base_url, requests):
        completed = run_adapter(["release", "--state", str(state_path)], adapter_environment(base_url))

    assert completed.returncode == 0, completed.stderr
    assert json.loads(state_path.read_text(encoding="utf-8"))["released"] is True
    assert [item["method"] for item in requests] == ["GET", "PUT", "GET", "DELETE", "GET"]


def test_vastai_google_drive_metadata_is_selected_and_fingerprinted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEDAI_COMPUTATION_PROVIDER", "vastai")
    monkeypatch.setenv("MEDAI_DRIVE_PROVIDER", "google-drive")
    monkeypatch.setenv("VAST_API_KEY", "vast-secret")
    monkeypatch.setenv("VASTAI_IMAGE", "registry.example/medai@sha256:image")
    monkeypatch.setenv("VASTAI_GOOGLE_DRIVE_CONNECTION_ID", "drive-7")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "run",
        provider="codex",
        repo=None,
        data="dataset-a",
        siliconflow_config=None,
        clouddrive=True,
    )

    assert config.drive_provider == "google-drive"
    assert config.cloud_source == "medai/dataset-a"
    assert config.computation_provider_config["values"]["VASTAI_GOOGLE_DRIVE_CONNECTION_ID"] == "drive-7"
    assert "vast-secret" not in json.dumps(config.computation_provider_config)


def test_vastai_cloud_pull_materializes_readonly_inventory_without_credentials(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    inventory = cloud_inventory("dataset-a")
    ssh_environment, command_log = fake_cloud_ssh_environment(tmp_path, inventory)
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("POST", "/api/v0/commands/rclone/"): {
                "success": True,
                "result_url": "https://signed.example/result-secret",
            },
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {
                    "actual_status": "running",
                    "status_msg": "Cloud Copy Operation Finished",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
                "MEDAI_DRIVE_PROVIDER": "google-drive",
            },
        )

    assert completed.returncode == 0, completed.stderr
    target_path = "/workspace/medai/test-run/data/dataset-a"
    assert completed.stdout.strip() == target_path
    copy = next(item for item in requests if item["path"] == "/api/v0/commands/rclone/")
    assert copy["body"] == {
        "instance_id": "instance-1",
        "src": "medai/dataset-a",
        "dst": "/workspace/medai/test-run/.staging/dataset-a",
        "selected": "drive-7",
        "transfer": "Cloud To Instance",
        "flags": [],
    }
    state_text = state_path.read_text(encoding="utf-8")
    state = json.loads(state_text)
    cloud = state["provider_state"]["cloud_drive"]
    assert cloud["drive"] == "google-drive"
    assert cloud["completed"] is True
    assert cloud["target_path"] == target_path
    assert cloud["inventory_path"] == "cloud-inventory.v1.json"
    assert json.loads((state_path.parent / "cloud-inventory.v1.json").read_text(encoding="utf-8"))["files"]
    assert "vast-secret" not in state_text
    assert "result-secret" not in state_text
    assert "mv --" in command_log.read_text(encoding="utf-8")


def test_vastai_cloud_pull_rejects_a_changed_inventory_on_repeat(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    first_inventory = cloud_inventory("dataset-a", "a" * 64)
    first_ssh_environment, _ = fake_cloud_ssh_environment(tmp_path, first_inventory)
    routes = {
        ("GET", "/api/v0/users/cloud_integrations"): [
            {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
        ],
        ("POST", "/api/v0/commands/rclone/"): {"success": True},
        ("GET", "/api/v0/instances/instance-1/"): {
            "instances": {
                "actual_status": "running",
                "status_msg": "Cloud Copy Operation Finished",
                "ssh_host": "host",
                "ssh_port": 22,
            }
        },
    }
    with vast_api(routes) as (base_url, _):
        initial = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                **first_ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )
    assert initial.returncode == 0, initial.stderr

    second_inventory = cloud_inventory("dataset-a", "b" * 64)
    second_ssh_environment, _ = fake_cloud_ssh_environment(tmp_path / "repeat", second_inventory)
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, _):
        repeated = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                **second_ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert repeated.returncode != 0
    assert "changed from the run baseline" in repeated.stderr
    assert json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]["completed"] is False


def test_vastai_replacement_rejects_google_drive_data_that_changed_from_its_baseline(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    baseline = json.loads(cloud_inventory("dataset-a", "a" * 64))
    inventory_path = state_path.parent / "cloud-inventory.v1.json"
    inventory_path.write_text(json.dumps(baseline), encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["released"] = True
    state["provider_state"]["cloud_drive"] = {
        "drive": "google-drive",
        "dataset": "dataset-a",
        "source_path": "medai/dataset-a",
        "connection_id": "drive-7",
        "staging_path": "/workspace/medai/test-run/.staging/dataset-a",
        "target_path": "/workspace/medai/test-run/data/dataset-a",
        "owned_paths": True,
        "inventory_path": "cloud-inventory.v1.json",
        "completed": True,
        "status": "completed",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    selected = offer("replacement")
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [selected]},
            ("PUT", "/api/v0/asks/replacement/"): {"success": True, "new_contract": "instance-2"},
            ("GET", "/api/v0/instances/instance-2/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, _):
        created = run_adapter(
            ["create", "--state", str(state_path), "--offer-id", "replacement"],
            adapter_environment(base_url),
        )
    assert created.returncode == 0, created.stderr
    replacement_cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert replacement_cloud["status"] == "replacement_pending"
    assert replacement_cloud["completed"] is False

    ssh_environment, _ = fake_cloud_ssh_environment(tmp_path / "replacement", cloud_inventory("dataset-a", "b" * 64))
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("POST", "/api/v0/commands/rclone/"): {"success": True},
            ("GET", "/api/v0/instances/instance-2/"): {
                "instances": {
                    "actual_status": "running",
                    "status_msg": "Cloud Copy Operation Finished",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
        }
    ) as (base_url, _):
        materialized = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert materialized.returncode != 0
    assert "changed from the run baseline" in materialized.stderr


def test_vastai_cloud_pull_rejects_an_unmatched_drive_connection(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "s3", "name": "wrong"}
            ]
        }
    ) as (base_url, _):
        completed = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert completed.returncode != 0
    assert "Google Drive connection" in completed.stderr


def test_vastai_cloud_timeout_cancels_before_exact_staging_cleanup(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, command_log = fake_cloud_ssh_environment(tmp_path, cloud_inventory("dataset-a"))
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("POST", "/api/v0/commands/rclone/"): {"success": True},
            ("DELETE", "/api/v0/commands/rclone/"): {"success": True},
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, requests):
        for name, value in {
            **adapter_environment(base_url),
            **ssh_environment,
            "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            "MEDAI_DRIVE_PROVIDER": "google-drive",
        }.items():
            monkeypatch.setenv(name, value)
        module = load_vastai_module()
        module.CLOUD_COPY_TIMEOUT_SECONDS = 0
        with pytest.raises(RuntimeError, match="timed out and was cancelled"):
            module.cloud_pull(argparse.Namespace(state=state_path, dataset="dataset-a"))

    assert [item["method"] for item in requests if item["path"] == "/api/v0/commands/rclone/"] == ["POST", "DELETE"]
    assert "/workspace/medai/test-run/.staging/dataset-a" in command_log.read_text(encoding="utf-8")
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["cancel_confirmed"] is True
    assert cloud["completed"] is False


def test_vastai_details_remain_outside_generic_flow_and_docs():
    skill_root = ROOT / "templates" / "skills" / "computation_provider"
    paths = [ROOT / "src" / "medai", ROOT / "templates", ROOT / "docs", ROOT / ".env.example"]
    forbidden = ("vastai", "vast.ai", "google-drive", "VAST_API_KEY", "VASTAI_")
    violations: list[Path] = []
    for path in paths:
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if (
                not candidate.is_file()
                or candidate.is_relative_to(skill_root)
                or (
                    candidate != ROOT / ".env.example"
                    and candidate.suffix not in {".md", ".py", ".json", ".toml"}
                )
            ):
                continue
            content = candidate.read_text(encoding="utf-8")
            if any(value in content for value in forbidden):
                violations.append(candidate.relative_to(ROOT))
    assert not violations
