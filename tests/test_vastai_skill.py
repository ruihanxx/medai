import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
    counts: dict[tuple[str, str], int] = {}

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
            if isinstance(response, list):
                index = counts.get(key, 0)
                response = response[index]
                counts[key] = index + 1
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
