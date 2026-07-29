from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil


def detect_resources(path: Path) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(path)
    resources: dict[str, Any] = {
        "cpu": {
            "logical_cores": psutil.cpu_count(logical=True) or 1,
            "physical_cores": psutil.cpu_count(logical=False),
            "architecture": platform.machine(),
        },
        "memory": {
            "total_gb": round(memory.total / 1024**3, 2),
            "available_gb": round(memory.available / 1024**3, 2),
        },
        "disk": {
            "total_gb": round(disk.total / 1024**3, 2),
            "free_gb": round(disk.free / 1024**3, 2),
        },
        "gpus": [],
    }

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return resources

    completed = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=index,name,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        resources["gpu_error"] = completed.stderr.strip()
        return resources

    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 4:
            continue
        resources["gpus"].append(
            {
                "index": int(fields[0]),
                "name": fields[1],
                "memory_total_gb": round(float(fields[2]) / 1024, 2),
                "memory_free_gb": round(float(fields[3]) / 1024, 2),
            }
        )
    return resources
