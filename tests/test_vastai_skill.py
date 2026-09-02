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
    cpu_cores_effective: float = 16.0,
    cpu_ram_mb: int = 65536,
    disk_space_gb: float = 128.0,
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
        "cpu_cores_effective": cpu_cores_effective,
        "cpu_ram": cpu_ram_mb,
        "disk_space": disk_space_gb,
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
    environment = {
        **os.environ,
        "VAST_API_KEY": "vast-secret",
        "VASTAI_IMAGE": "registry.example/medai@sha256:image",
        "VASTAI_API_BASE_URL": base_url,
    }
    environment.pop("COMPUTATION_PROVIDER_SSH_IDENTITY_FILE", None)
    return environment


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


def test_vastai_inventory_program_preserves_multiple_dataset_subtrees(tmp_path: Path):
    root = tmp_path / "dataset"
    (root / "dataset-a").mkdir(parents=True)
    (root / "dataset-b").mkdir(parents=True)
    (root / "dataset-a" / "records.csv").write_text("a", encoding="utf-8")
    (root / "dataset-b" / "records.csv").write_text("b", encoding="utf-8")
    module = load_vastai_module()

    completed = subprocess.run(
        [sys.executable, "-c", module.INVENTORY_PROGRAM, "inventory", str(root), "dataset-a"],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    inventory = json.loads(completed.stdout)
    assert [item["path"] for item in inventory["files"]] == [
        "dataset-a/records.csv",
        "dataset-b/records.csv",
    ]


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
                    "creation_uncertain": False,
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
printf 'ARGS %s\n' "$*" >> "$MEDAI_TEST_CLOUD_COMMAND_LOG"
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


def test_vastai_cpu_only_search_bypasses_gpu_defaults_and_uses_cpu_capacity(
    tmp_path: Path,
):
    del tmp_path
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {
                "offers": [
                    offer("expensive", dph_total=0.9),
                    offer("cheap", dph_total=0.4, total_flops=5.0),
                    offer("zero-gpu", gpu_count=0, dph_total=0.1),
                    offer("few-cores", cpu_cores_effective=8, dph_total=0.2),
                    offer("little-ram", cpu_ram_mb=32768, dph_total=0.2),
                    offer("little-disk", disk_space_gb=64, dph_total=0.2),
                ]
            }
        }
    ) as (base_url, requests):
        completed = run_adapter(
            [
                "search",
                "--cpu-only",
                "--min-cpu-cores",
                "12",
                "--min-cpu-ram-gb",
                "64",
                "--disk-gb",
                "100",
            ],
            {
                **adapter_environment(base_url),
                "VASTAI_DEFAULT_GPU_COUNT": "8",
                "VASTAI_MIN_GPU_RAM_GB": "80",
            },
        )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert [item["id"] for item in payload["offers"]] == ["cheap", "expensive"]
    body = requests[0]["body"]
    assert body["num_gpus"] == {"gte": 1}
    assert body["gpu_ram"] == {"gte": 1024}
    assert body["cpu_cores_effective"] == {"gte": 12}
    assert body["cpu_ram"] == {"gte": 64 * 1024}
    assert body["disk_space"] == {"gte": 100}


@pytest.mark.parametrize(
    "arguments, message",
    [
        (
            ["--cpu-only", "--min-cpu-cores", "8", "--gpu-count", "1"],
            "cannot be combined with GPU resource arguments",
        ),
        (["--cpu-only"], "requires a positive --min-cpu-cores"),
        (["--min-cpu-cores", "8"], "requires --cpu-only"),
    ],
)
def test_vastai_cpu_only_rejects_conflicting_or_incomplete_parameters(
    arguments: list[str], message: str
):
    completed = run_adapter(
        ["search", *arguments],
        adapter_environment("http://127.0.0.1:1"),
    )

    assert completed.returncode != 0
    assert message in completed.stderr


def test_vastai_cpu_only_create_records_cpu_request_and_effective_capacity(
    tmp_path: Path,
):
    state_path = tmp_path / "remote_compute" / "instance.json"
    ssh_environment, _ = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    selected = offer(
        "cpu-host",
        gpu_name="RTX 3090",
        gpu_ram_mb=24576,
        cpu_cores_effective=20.0,
        cpu_ram_mb=98304,
        disk_space_gb=256,
        total_flops=1.0,
        dph_total=0.45,
    )
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [selected]},
            ("PUT", "/api/v0/asks/cpu-host/"): {
                "success": True,
                "new_contract": "instance-cpu",
            },
            ("GET", "/api/v0/instances/instance-cpu/"): {
                "instances": {
                    "actual_status": "running",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
        }
    ) as (base_url, _):
        completed = run_adapter(
            [
                "create",
                "--state",
                str(state_path),
                "--offer-id",
                "cpu-host",
                "--cpu-only",
                "--min-cpu-cores",
                "12",
                "--min-cpu-ram-gb",
                "64",
                "--disk-gb",
                "100",
            ],
            {**adapter_environment(base_url), **ssh_environment},
        )

    assert completed.returncode == 0, completed.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    requested = state["provider_state"]["requested"]
    recorded_offer = state["provider_state"]["selected_offer"]
    assert requested["cpu_only"] is True
    assert requested["min_cpu_cores"] == 12
    assert requested["gpu_count"] == 1
    assert requested["min_gpu_ram_gb"] == 1
    assert recorded_offer["cpu_cores_effective"] == 20.0
    assert recorded_offer["disk_space_gb"] == 256.0
    validated = run_adapter(
        ["validate-state", "--state", str(state_path)],
        adapter_environment("http://127.0.0.1:1"),
    )
    assert validated.returncode == 0, validated.stderr


def test_vastai_cpu_only_fallback_compares_cpu_ram_and_disk_not_gpu_flops():
    module = load_vastai_module()
    primary = module._offer_record(
        offer("primary", cpu_cores_effective=12, total_flops=80, dph_total=0.3)
    )
    lower_gpu_flops = module._offer_record(
        offer("fallback", cpu_cores_effective=16, total_flops=5, dph_total=0.8)
    )
    lower_cpu = module._offer_record(
        offer("lower-cpu", cpu_cores_effective=8, total_flops=100, dph_total=0.2)
    )

    assert module._stronger_or_equal(lower_gpu_flops, primary, cpu_only=True)
    assert not module._stronger_or_equal(lower_gpu_flops, primary)
    assert not module._stronger_or_equal(lower_cpu, primary, cpu_only=True)


def test_vastai_cpu_only_replacement_preserves_recorded_cpu_ram_and_disk(
    tmp_path: Path, monkeypatch
):
    module = load_vastai_module()
    selected = module._offer_record(
        offer(
            "old",
            cpu_cores_effective=19.2,
            cpu_ram_mb=98304,
            disk_space_gb=256,
            total_flops=80,
        )
    )
    replacement = module._offer_record(
        offer(
            "new",
            cpu_cores_effective=20,
            cpu_ram_mb=98304,
            disk_space_gb=256,
            total_flops=5,
            dph_total=0.8,
        )
    )
    state = {
        "provider_state": {
            "requested": {
                "cpu_only": True,
                "min_cpu_cores": 12,
                "gpu_name": None,
                "gpu_count": 1,
                "min_gpu_ram_gb": 1,
                "min_cpu_ram_gb": 64,
                "max_dph": 2.0,
                "min_reliability": 0.99,
                "disk_gb": 100,
                "image": "image",
            },
            "selected_offer": selected,
        }
    }
    specifications: list[dict[str, Any]] = []

    def fake_search(specification, offer_id=None):
        assert offer_id is None
        specifications.append(specification)
        return [replacement]

    monkeypatch.setattr(module, "search_offers", fake_search)
    args = module._replacement_args(tmp_path / "instance.json", state)

    assert specifications[0]["min_cpu_cores"] == 20
    assert specifications[0]["min_cpu_ram_gb"] == 96
    assert specifications[0]["disk_gb"] == 256
    assert specifications[0]["min_gpu_ram_gb"] == 1
    assert args.cpu_only is True
    assert args.gpu_name is None
    assert args.gpu_count is None
    assert args.min_gpu_ram_gb is None


def test_vastai_create_records_nonsecret_state_and_requested_container(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    ssh_environment, _ = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    selected = offer("12345")
    identity = tmp_path / "ssh" / "medai-vast"
    identity.parent.mkdir()
    identity.write_text("local-private-secret", encoding="utf-8")
    public_key = "ssh-ed25519 ZmFrZS1wdWJsaWMta2V5 medai-vast"
    Path(f"{identity}.pub").write_text(public_key + "\n", encoding="utf-8")
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [selected]},
            ("GET", "/api/v0/ssh"): [
                {
                    "id": 7,
                    "public_key": public_key,
                    "private_key": "provider-private-secret",
                    "deleted_at": None,
                }
            ],
            ("PUT", "/api/v0/asks/12345/"): {"success": True, "new_contract": "instance-1"},
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["create", "--state", str(state_path), "--offer-id", "12345"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "COMPUTATION_PROVIDER_SSH_IDENTITY_FILE": str(identity),
            },
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "instance-1"
    selection = next(item for item in requests if item["path"] == "/api/v0/bundles")
    assert selection["body"]["ask_contract_id"] == {"eq": 12345}
    assert selection["body"]["limit"] == 1
    created = next(item for item in requests if item["path"] == "/api/v0/asks/12345/")
    assert created["body"]["disk"] == 64
    assert created["body"]["image"] == "registry.example/medai@sha256:image"
    assert created["body"]["runtype"] == "ssh"
    assert created["body"]["target_state"] == "running"
    assert "ssh-ed25519 ZmFrZS1wdWJsaWMta2V5" in created["body"]["onstart"]
    assert "local-private-secret" not in json.dumps(requests)
    assert "provider-private-secret" not in json.dumps(created)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["provider"] == "vastai"
    assert state["provider_state"]["instance_id"] == "instance-1"
    assert state["provider_state"]["requested"]["min_gpu_ram_gb"] == 24
    assert "/workspace/medai/" in state["provider_state"]["remote_working_dir"]
    assert "vast-secret" not in state_path.read_text(encoding="utf-8")
    assert "ZmFrZS1wdWJsaWMta2V5" not in state_path.read_text(encoding="utf-8")


def test_vastai_create_waits_through_an_initial_null_status(tmp_path: Path, monkeypatch):
    state_path = tmp_path / "instance.json"
    statuses = iter([None, "loading", "running"])
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [offer("primary")]},
            ("PUT", "/api/v0/asks/primary/"): {"success": True, "new_contract": "instance-1"},
            ("GET", "/api/v0/instances/instance-1/"): lambda _: {
                "instances": {"actual_status": next(statuses)}
            },
        }
    ) as (base_url, _):
        for name, value in adapter_environment(base_url).items():
            monkeypatch.setenv(name, value)
        module = load_vastai_module()
        monkeypatch.setattr(module.time, "sleep", lambda _: None)
        probes = []

        def successful_probe(state, action, arguments):
            probes.append((state["provider_state"]["instance_id"], action, arguments))
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(module, "_ssh_command", successful_probe)
        instance_id = module.create_instance(
            module.build_parser().parse_args(
                ["create", "--state", str(state_path), "--offer-id", "primary"]
            )
        )

    assert instance_id == "instance-1"
    assert probes == [("instance-1", "exec", ["--", "true"])]


def test_vastai_create_marks_running_instance_failed_when_ssh_is_not_ready(
    tmp_path: Path, monkeypatch
):
    state_path = tmp_path / "remote_compute" / "instance.json"
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [offer("primary")]},
            ("PUT", "/api/v0/asks/primary/"): {
                "success": True,
                "new_contract": "instance-1",
            },
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running"}
            },
        }
    ) as (base_url, _):
        for name, value in adapter_environment(base_url).items():
            monkeypatch.setenv(name, value)
        module = load_vastai_module()
        monkeypatch.setattr(module, "SSH_READY_TIMEOUT_SECONDS", 0)
        monkeypatch.setattr(
            module,
            "_ssh_command",
            lambda *_: subprocess.CompletedProcess([], 255, "", "probe failed"),
        )

        with pytest.raises(RuntimeError, match="did not become SSH-ready"):
            module.create_instance(
                module.build_parser().parse_args(
                    ["create", "--state", str(state_path), "--offer-id", "primary"]
                )
            )

        failed = json.loads(state_path.read_text(encoding="utf-8"))
        assert failed["released"] is False
        assert failed["provider_state"]["creation_failed"] is True
        assert failed["provider_state"]["creation_failure"] == (
            "Vast instance reached running but did not become SSH-ready"
        )


def test_vastai_refuses_rental_when_explicit_ssh_key_is_not_registered(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    identity = tmp_path / "medai-vast"
    identity.write_text("local-private-secret", encoding="utf-8")
    Path(f"{identity}.pub").write_text(
        "ssh-ed25519 ZmFrZS1wdWJsaWMta2V5 medai-vast\n", encoding="utf-8"
    )
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [offer("primary")]},
            ("GET", "/api/v0/ssh"): [
                {
                    "id": 8,
                    "public_key": "ssh-ed25519 ZGlmZmVyZW50LWtleQ== other",
                    "deleted_at": None,
                }
            ],
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["create", "--state", str(state_path), "--offer-id", "primary"],
            {
                **adapter_environment(base_url),
                "COMPUTATION_PROVIDER_SSH_IDENTITY_FILE": str(identity),
            },
        )

    assert completed.returncode != 0
    assert "not registered" in completed.stderr
    assert not state_path.exists()
    assert not any(item["method"] == "PUT" for item in requests)
    assert "local-private-secret" not in completed.stderr


def test_vastai_uses_one_fallback_only_after_explicit_primary_no_inventory(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    ssh_environment, _ = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    primary = offer("primary", total_flops=80.0)
    fallback = offer("fallback", gpu_name="RTX 6000 Ada", gpu_ram_mb=49152, total_flops=91.0)
    with vast_api(
        {
            ("POST", "/api/v0/bundles"): {"offers": [primary, fallback]},
            ("PUT", "/api/v0/asks/primary/"): (409, {"msg": "offer is no longer available"}),
            ("GET", "/api/v1/instances/"): {"instances": []},
            ("PUT", "/api/v0/asks/fallback/"): {"success": True, "new_contract": "instance-2"},
            ("GET", "/api/v0/instances/instance-2/"): {
                "instances": {
                    "actual_status": "running",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
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
            {**adapter_environment(base_url), **ssh_environment},
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


def test_vastai_power_off_accepts_exited_when_control_plane_is_stopped(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    vast_state(state_path)
    states = iter(
        [
            {"actual_status": "running", "cur_state": "running"},
            {"actual_status": "exited", "cur_state": "stopped"},
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: {
                "instances": next(states)
            },
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["power-off", "--state", str(state_path)], adapter_environment(base_url)
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "stopped"
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"}
    ]


def test_vastai_power_on_waits_through_exited_when_control_plane_is_running(
    tmp_path: Path, monkeypatch
):
    state_path = tmp_path / "instance.json"
    vast_state(state_path)
    states = iter(
        [
            {"actual_status": "exited", "cur_state": "stopped"},
            {"actual_status": "exited", "cur_state": "running"},
            {"actual_status": "running", "cur_state": "running"},
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: {
                "instances": next(states)
            },
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
        }
    ) as (base_url, requests):
        for name, value in adapter_environment(base_url).items():
            monkeypatch.setenv(name, value)
        module = load_vastai_module()
        monkeypatch.setattr(module.time, "sleep", lambda _: None)
        status = module.power_on_instance(argparse.Namespace(state=state_path))

    assert status == "running"
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "running"}
    ]


def test_vastai_autoresearch_pool_creates_member_when_retained_gpu_is_unavailable(
    tmp_path: Path,
):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["provider_state"]["cloud_drive"] = {
        "completed": True,
        "status": "completed",
        "drive": "google-drive",
        "dataset": "dataset-a",
        "source_path": "medai/dataset-a",
        "target_path": "/workspace/medai/test-run/data/dataset-a",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"inputs": {"workflow": "autoresearch"}, "resume_count": 0}),
        encoding="utf-8",
    )
    replacement = offer("replacement")
    ssh_environment, _ = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )

    def manage_original(requests):
        if requests[-1]["body"] == {"state": "running"}:
            return {
                "success": False,
                "msg": "Required resources are currently unavailable, state change queued.",
            }
        return {"success": True}

    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "stopped", "cur_state": "stopped"}
            },
            ("PUT", "/api/v0/instances/instance-1/"): manage_original,
            ("POST", "/api/v0/bundles"): {"offers": [replacement]},
            ("PUT", "/api/v0/asks/replacement/"): {
                "success": True,
                "new_contract": "instance-2",
            },
            ("GET", "/api/v0/instances/instance-2/"): {
                "instances": {
                    "actual_status": "running",
                    "cur_state": "running",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["power-on", "--state", str(state_path)],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_MAX_CAMPAIGN_INSTANCES": "3",
            },
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "created": True,
        "instance_id": "instance-2",
        "materialization_required": True,
        "pool_size": 2,
        "status": "running",
        "switched": True,
    }
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["provider_state"]["instance_id"] == "instance-2"
    assert [
        entry["instance_id"] for entry in saved["provider_state"]["instance_pool"]
    ] == ["instance-1", "instance-2"]
    assert saved["provider_state"]["instance_pool"][0]["cloud_drive"]["completed"] is True
    assert saved["provider_state"]["instance_pool"][1]["cloud_drive"]["completed"] is False
    assert [
        request["body"]
        for request in requests
        if request["path"] == "/api/v0/instances/instance-1/"
        and request["method"] == "PUT"
    ] == [{"state": "running"}, {"state": "stopped"}]


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
            {"instances": []},
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: next(responses),
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
            ("DELETE", "/api/v0/instances/instance-1/"): {"success": True},
            ("GET", "/api/v1/instances/"): {"instances": []},
        }
    ) as (base_url, requests):
        completed = run_adapter(["release", "--state", str(state_path)], adapter_environment(base_url))

    assert completed.returncode == 0, completed.stderr
    assert json.loads(state_path.read_text(encoding="utf-8"))["released"] is True
    assert [item["method"] for item in requests] == ["GET", "PUT", "GET", "DELETE", "GET", "GET"]


def test_vastai_autoresearch_release_destroys_every_pool_member(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    provider_state = state["provider_state"]
    first = {
        name: provider_state[name]
        for name in (
            "instance_id",
            "label",
            "selected_offer",
            "creation_uncertain",
        )
    }
    first["failed_create_retries"] = 0
    first["released"] = False
    second = {
        **first,
        "instance_id": "instance-2",
        "label": "medai-test-run-pool-002",
        "selected_offer": {**first["selected_offer"], "id": "secondary"},
    }
    provider_state.update(
        {
            "instance_pool_enabled": True,
            "instance_pool": [first, second],
            "active_pool_index": 0,
            "active_instance_released": False,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "inputs": {"workflow": "autoresearch"},
                "resume_count": 0,
            }
        ),
        encoding="utf-8",
    )
    first_responses = iter(
        [
            {"instances": {"actual_status": "stopped", "cur_state": "stopped"}},
            (404, {"msg": "not found"}),
        ]
    )
    second_responses = iter(
        [
            {"instances": {"actual_status": "running", "cur_state": "running"}},
            {"instances": {"actual_status": "stopped", "cur_state": "stopped"}},
            (404, {"msg": "not found"}),
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: next(
                first_responses
            ),
            ("GET", "/api/v0/instances/instance-2/"): lambda _: next(
                second_responses
            ),
            ("PUT", "/api/v0/instances/instance-2/"): {"success": True},
            ("DELETE", "/api/v0/instances/instance-1/"): {"success": True},
            ("DELETE", "/api/v0/instances/instance-2/"): {"success": True},
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["release", "--state", str(state_path)],
            {
                **adapter_environment(base_url),
                "VASTAI_MAX_CAMPAIGN_INSTANCES": "1",
            },
        )

    assert completed.returncode == 0, completed.stderr
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["released"] is True
    assert all(
        entry["released"] is True
        for entry in saved["provider_state"]["instance_pool"]
    )
    assert [
        request["path"] for request in requests if request["method"] == "DELETE"
    ] == [
        "/api/v0/instances/instance-1/",
        "/api/v0/instances/instance-2/",
    ]


def test_vastai_release_keeps_ownership_when_empty_show_conflicts_with_listing(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    vast_state(state_path)
    responses = iter(
        [
            {"instances": {"actual_status": "running"}},
            {"instances": {"actual_status": "stopped"}},
            {"instances": []},
        ]
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): lambda _: next(responses),
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
            ("DELETE", "/api/v0/instances/instance-1/"): {"success": True},
            ("GET", "/api/v1/instances/"): {"instances": [{"id": "instance-1"}]},
        }
    ) as (base_url, _):
        completed = run_adapter(
            ["release", "--state", str(state_path)], adapter_environment(base_url)
        )

    assert completed.returncode != 0
    assert "remains visible" in completed.stderr
    assert json.loads(state_path.read_text(encoding="utf-8"))["released"] is False


def test_vastai_prefers_the_direct_ssh_endpoint(tmp_path: Path):
    state_path = tmp_path / "instance.json"
    vast_state(state_path)
    ssh_environment, command_log = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {
                    "actual_status": "running",
                    "ssh_host": "ssh1.vast.ai",
                    "ssh_port": 10022,
                    "public_ipaddr": "203.0.113.10",
                    "machine_dir_ssh_port": 61999,
                }
            }
        }
    ) as (base_url, _):
        completed = run_adapter(
            ["exec", "--state", str(state_path), "--", "true"],
            {**adapter_environment(base_url), **ssh_environment},
        )

    assert completed.returncode == 0, completed.stderr
    command_text = command_log.read_text(encoding="utf-8")
    assert "203.0.113.10" in command_text
    assert "61999" in command_text
    assert "ssh1.vast.ai" not in command_text


def test_vastai_falls_back_to_proxy_only_after_direct_authentication_failure(
    tmp_path: Path,
):
    state_path = tmp_path / "instance.json"
    vast_state(state_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "ssh.log"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MEDAI_TEST_SSH_LOG"
if [[ "$*" == *"203.0.113.10"* ]]; then
    exit 255
fi
exit 0
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    with vast_api(
        {
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {
                    "actual_status": "running",
                    "ssh_host": "ssh1.vast.ai",
                    "ssh_port": 10022,
                    "public_ipaddr": "203.0.113.10",
                    "machine_dir_ssh_port": 61999,
                }
            }
        }
    ) as (base_url, _):
        completed = run_adapter(
            ["exec", "--state", str(state_path), "--", "true"],
            {
                **adapter_environment(base_url),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "MEDAI_TEST_SSH_LOG": str(command_log),
            },
        )

    assert completed.returncode == 0, completed.stderr
    command_text = command_log.read_text(encoding="utf-8")
    assert command_text.count("203.0.113.10") == 1
    assert command_text.count("ssh1.vast.ai") == 2


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
    assert get_provider_adapter("vastai").drive("google-drive").cloud_pull_handoff is True


def test_vastai_cloud_prepare_stops_only_after_ssh_and_path_preflight(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, command_log = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    lifecycle = {"status": "running"}

    def show_instance(_requests):
        return {
            "instances": {
                "actual_status": lifecycle["status"],
                "cur_state": lifecycle["status"],
                "ssh_host": "host",
                "ssh_port": 22,
            }
        }

    def manage_instance(requests):
        lifecycle["status"] = requests[-1]["body"]["state"]
        return {"success": True}

    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): show_instance,
            ("PUT", "/api/v0/instances/instance-1/"): manage_instance,
        }
    ) as (base_url, requests):
        prepared = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--prepare"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert prepared.returncode == 0, prepared.stderr
    assert lifecycle["status"] == "stopped"
    assert not [item for item in requests if item["method"] == "POST"]
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"}
    ]
    command_text = command_log.read_text(encoding="utf-8")
    assert "medai-cloud-write-probe" in command_text
    assert "/workspace/medai/test-run/data/dataset-a" in command_text
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["handoff_ready"] is True
    assert cloud["status"] == "new"


def test_vastai_cloud_prepare_does_not_stop_when_ssh_initialization_fails(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh = fake_bin / "ssh"
    ssh.write_text("#!/usr/bin/env bash\nexit 255\n", encoding="utf-8")
    ssh.chmod(0o755)
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {"actual_status": "running", "ssh_host": "host", "ssh_port": 22}
            },
        }
    ) as (base_url, requests):
        prepared = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--prepare"],
            {
                **adapter_environment(base_url),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert prepared.returncode != 0
    assert not [item for item in requests if item["method"] == "PUT"]
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["status"] == "new"
    assert "handoff_ready" not in cloud


def test_vastai_cloud_monitor_requires_prepared_stopped_instance(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
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
        monitored = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--monitor"],
            {
                **adapter_environment(base_url),
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert monitored.returncode != 0
    assert "requires a completed preparation" in monitored.stderr


def test_vastai_cloud_monitor_restarts_then_materializes_after_offline_copy(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, command_log = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    lifecycle = {"status": "running", "copy_requested": False}

    def show_instance(_requests):
        message = "Cloud Copy Operation Complete" if lifecycle["copy_requested"] else ""
        return {
            "instances": {
                "actual_status": lifecycle["status"],
                "cur_state": lifecycle["status"],
                "status_msg": message,
                "ssh_host": "host",
                "ssh_port": 22,
            }
        }

    def manage_instance(requests):
        lifecycle["status"] = requests[-1]["body"]["state"]
        return {"success": True}

    def start_copy(_requests):
        lifecycle["copy_requested"] = True
        return {"success": True}

    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): show_instance,
            ("PUT", "/api/v0/instances/instance-1/"): manage_instance,
            ("POST", "/api/v0/commands/rclone/"): start_copy,
        }
    ) as (base_url, requests):
        prepared = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--prepare"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )
        monitored = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--monitor"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert prepared.returncode == 0, prepared.stderr
    assert monitored.returncode == 0, monitored.stderr
    assert lifecycle["status"] == "running"
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"},
        {"state": "running"},
    ]
    assert "cloud-copy: Cloud Copy Operation Complete" in monitored.stdout
    assert "medai-cloud-inventory" in command_log.read_text(encoding="utf-8")
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["completed"] is True
    assert "handoff_ready" not in cloud


def test_vastai_cloud_monitor_restarts_before_reporting_copy_failure(tmp_path: Path):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, _ = fake_cloud_ssh_environment(tmp_path, cloud_inventory("dataset-a"))
    lifecycle = {"status": "running", "copy_requested": False}

    def show_instance(_requests):
        message = "Cloud Copy Operation Failed" if lifecycle["copy_requested"] else ""
        return {
            "instances": {
                "actual_status": lifecycle["status"],
                "cur_state": lifecycle["status"],
                "status_msg": message,
                "ssh_host": "host",
                "ssh_port": 22,
            }
        }

    def manage_instance(requests):
        lifecycle["status"] = requests[-1]["body"]["state"]
        return {"success": True}

    def start_copy(_requests):
        lifecycle["copy_requested"] = True
        return {"success": True}

    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): show_instance,
            ("PUT", "/api/v0/instances/instance-1/"): manage_instance,
            ("POST", "/api/v0/commands/rclone/"): start_copy,
        }
    ) as (base_url, requests):
        prepared = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--prepare"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )
        monitored = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a", "--monitor"],
            {
                **adapter_environment(base_url),
                **ssh_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert prepared.returncode == 0, prepared.stderr
    assert monitored.returncode != 0
    assert "cloud copy failed" in monitored.stderr
    assert lifecycle["status"] == "running"
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"},
        {"state": "running"},
    ]
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["status"] == "failed"
    assert cloud["completed"] is False


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
                    "status_msg": "Cloud Copy Operation Complete",
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
    assert completed.stdout.splitlines()[-1] == target_path
    assert "cloud-copy: Cloud Copy Operation Complete" in completed.stdout
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

    second_tmp = tmp_path / "second-dataset"
    second_tmp.mkdir()
    second_environment, _ = fake_cloud_ssh_environment(
        second_tmp, cloud_inventory("dataset-b", digest="b" * 64)
    )
    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("POST", "/api/v0/commands/rclone/"): {"success": True},
            ("GET", "/api/v0/instances/instance-1/"): {
                "instances": {
                    "actual_status": "running",
                    "status_msg": "Cloud Copy Operation Complete",
                    "ssh_host": "host",
                    "ssh_port": 22,
                }
            },
        }
    ) as (base_url, _):
        second = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-b"],
            {
                **adapter_environment(base_url),
                **second_environment,
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
                "MEDAI_DRIVE_PROVIDER": "google-drive",
            },
        )

    assert second.returncode == 0, second.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["provider_state"]["cloud_drives"]) == {"dataset-a", "dataset-b"}
    assert state["provider_state"]["cloud_drives"]["dataset-a"]["completed"] is True
    assert state["provider_state"]["cloud_drives"]["dataset-b"]["completed"] is True
    assert (state_path.parent / "cloud-inventory.dataset-b.v1.json").is_file()


def test_vastai_cloud_pull_restarts_same_instance_when_staging_is_not_visible(
    tmp_path: Path,
):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_log = tmp_path / "ssh.log"
    staging_probe = tmp_path / "staging-probed"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="${!#}"
printf '%s\n' "$command" >> "$MEDAI_TEST_SSH_LOG"
if [[ "$command" == *"test -d"* ]] && [[ ! -e "$MEDAI_TEST_STAGING_PROBE" ]]; then
    touch "$MEDAI_TEST_STAGING_PROBE"
    exit 1
fi
if [[ "$command" == *"medai-cloud-inventory"* ]]; then
    printf '%s\n' "$MEDAI_TEST_CLOUD_INVENTORY"
fi
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    show_count = 0

    def show_instance(_):
        nonlocal show_count
        show_count += 1
        if show_count in {6, 7}:
            status = {"actual_status": "exited", "cur_state": "stopped"}
        else:
            status = {"actual_status": "running", "cur_state": "running"}
        return {
            "instances": {
                **status,
                "status_msg": "Cloud Copy Operation Complete",
                "ssh_host": "host",
                "ssh_port": 22,
            }
        }

    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("POST", "/api/v0/commands/rclone/"): {"success": True},
            ("GET", "/api/v0/instances/instance-1/"): show_instance,
            ("PUT", "/api/v0/instances/instance-1/"): {"success": True},
        }
    ) as (base_url, requests):
        completed = run_adapter(
            ["cloud-pull", "--state", str(state_path), "--dataset", "dataset-a"],
            {
                **adapter_environment(base_url),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "MEDAI_TEST_CLOUD_INVENTORY": cloud_inventory("dataset-a"),
                "MEDAI_TEST_SSH_LOG": str(ssh_log),
                "MEDAI_TEST_STAGING_PROBE": str(staging_probe),
                "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
            },
        )

    assert completed.returncode == 0, completed.stderr
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"},
        {"state": "running"},
    ]
    assert staging_probe.is_file()
    assert json.loads(state_path.read_text(encoding="utf-8"))["provider_state"][
        "cloud_drive"
    ]["completed"] is True


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
    ready_ssh_environment, _ = fake_cloud_ssh_environment(
        tmp_path / "create", cloud_inventory("dataset-a")
    )
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
            {**adapter_environment(base_url), **ready_ssh_environment},
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


def test_vastai_offline_monitor_timeout_restarts_before_exact_cleanup(
    tmp_path: Path, monkeypatch
):
    state_path = tmp_path / "remote_compute" / "instance.json"
    vast_state(state_path)
    ssh_environment, command_log = fake_cloud_ssh_environment(
        tmp_path, cloud_inventory("dataset-a")
    )
    lifecycle = {"status": "running"}

    def show_instance(_requests):
        return {
            "instances": {
                "actual_status": lifecycle["status"],
                "cur_state": lifecycle["status"],
                "ssh_host": "host",
                "ssh_port": 22,
            }
        }

    def manage_instance(requests):
        lifecycle["status"] = requests[-1]["body"]["state"]
        return {"success": True}

    with vast_api(
        {
            ("GET", "/api/v0/users/cloud_integrations"): [
                {"id": "drive-7", "cloud_type": "drive", "name": "dedicated"}
            ],
            ("GET", "/api/v0/instances/instance-1/"): show_instance,
            ("PUT", "/api/v0/instances/instance-1/"): manage_instance,
            ("POST", "/api/v0/commands/rclone/"): {"success": True},
            ("DELETE", "/api/v0/commands/rclone/"): {"success": True},
        }
    ) as (base_url, requests):
        for name, value in {
            **adapter_environment(base_url),
            **ssh_environment,
            "VASTAI_GOOGLE_DRIVE_CONNECTION_ID": "drive-7",
        }.items():
            monkeypatch.setenv(name, value)
        module = load_vastai_module()
        module.CLOUD_COPY_TIMEOUT_SECONDS = 0
        module.cloud_pull(
            argparse.Namespace(state=state_path, dataset="dataset-a", prepare=True, monitor=False)
        )
        with pytest.raises(RuntimeError, match="timed out and was cancelled"):
            module.cloud_pull(
                argparse.Namespace(state=state_path, dataset="dataset-a", prepare=False, monitor=True)
            )

    assert lifecycle["status"] == "running"
    assert [item["method"] for item in requests if item["path"] == "/api/v0/commands/rclone/"] == [
        "POST",
        "DELETE",
    ]
    assert [item["body"] for item in requests if item["method"] == "PUT"] == [
        {"state": "stopped"},
        {"state": "running"},
    ]
    assert "/workspace/medai/test-run/.staging/dataset-a" in command_log.read_text(encoding="utf-8")
    cloud = json.loads(state_path.read_text(encoding="utf-8"))["provider_state"]["cloud_drive"]
    assert cloud["cancel_confirmed"] is True
    assert cloud["status"] == "failed"


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
