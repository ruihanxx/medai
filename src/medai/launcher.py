from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Union


class LauncherError(RuntimeError):
    pass


@dataclass(frozen=True)
class PythonInfo:
    executable: Path
    major: int
    minor: int
    architecture: str

    @property
    def fingerprint(self) -> str:
        return f"{self.major}.{self.minor}:{self.architecture}"


@dataclass(frozen=True)
class RuntimeCommands:
    python: Path
    mineru: Path
    models_download: Path


def _project_root() -> Path:
    configured_root = os.environ.get("MEDAI_PROJECT_ROOT")
    if configured_root:
        configured = Path(configured_root).expanduser().resolve()
        if (configured / "docker" / "Dockerfile").is_file():
            return configured
        raise LauncherError(f"MEDAI_PROJECT_ROOT is not a MedAI source checkout: {configured}")
    candidates = []
    candidates.append(Path(__file__).resolve().parents[2])
    candidates.extend((Path.cwd(), *Path.cwd().parents))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "docker" / "Dockerfile").is_file():
            return resolved
    raise LauncherError(
        "Could not locate the MedAI source checkout; set MEDAI_PROJECT_ROOT to its path"
    )


def _runtime_commands(venv: Path, system: Optional[str] = None) -> RuntimeCommands:
    system = system or platform.system()
    if system == "Windows":
        scripts = venv / "Scripts"
        return RuntimeCommands(
            python=scripts / "python.exe",
            mineru=scripts / "mineru.exe",
            models_download=scripts / "mineru-models-download.exe",
        )
    scripts = venv / "bin"
    return RuntimeCommands(
        python=scripts / "python",
        mineru=scripts / "mineru",
        models_download=scripts / "mineru-models-download",
    )


def _command_path(value: str) -> Optional[Path]:
    resolved = shutil.which(value)
    if resolved:
        return Path(resolved).resolve()
    path = Path(value).expanduser()
    return path.resolve() if path.is_file() else None


def _command_output(
    command: Sequence[Union[str, Path]], env: Optional[dict[str, str]] = None
) -> str:
    completed = subprocess.run(
        [str(part) for part in command],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _python_info(executable: Path) -> PythonInfo:
    output = _command_output(
        [
            executable,
            "-c",
            (
                "import platform, sys; "
                'print(f"{sys.version_info.major}.{sys.version_info.minor}:"'
                'f"{platform.machine()}")'
            ),
        ]
    )
    try:
        version, architecture = output.rsplit(":", maxsplit=1)
        major, minor = (int(part) for part in version.split(".", maxsplit=1))
    except (TypeError, ValueError) as exc:
        raise LauncherError(f"Could not inspect host Python: {executable}") from exc
    return PythonInfo(
        executable=executable,
        major=major,
        minor=minor,
        architecture=architecture.casefold(),
    )


def _native_homebrew_install_command(brew: Path, arch: Path) -> list[str]:
    if not arch.is_file():
        raise LauncherError(
            "Apple Silicon Python bootstrap requires /usr/bin/arch."
        )
    return [str(arch), "-arm64", str(brew), "install", "python@3.12"]


def _host_is_apple_silicon() -> bool:
    if platform.system() != "Darwin":
        return False
    if platform.machine().casefold() in {"arm64", "aarch64"}:
        return True
    arch = Path("/usr/bin/arch")
    true_command = Path("/usr/bin/true")
    if arch.is_file() and true_command.is_file():
        arm_probe = subprocess.run(
            [str(arch), "-arm64", str(true_command)],
            check=False,
            capture_output=True,
        )
        if arm_probe.returncode == 0:
            return True
    sysctl_value = shutil.which("sysctl")
    sysctl = Path(sysctl_value) if sysctl_value else Path("/usr/sbin/sysctl")
    if not sysctl.is_file():
        return False
    translated = subprocess.run(
        [str(sysctl), "-in", "sysctl.proc_translated"],
        check=False,
        capture_output=True,
        text=True,
    )
    return translated.stdout.strip() == "1"


def _macos_major_version() -> Optional[int]:
    if platform.system() != "Darwin":
        return None
    sw_vers = Path("/usr/bin/sw_vers")
    version = (
        _command_output([sw_vers, "-productVersion"])
        if sw_vers.is_file()
        else platform.mac_ver()[0]
    )
    return int(version.split(".", maxsplit=1)[0]) if version else None


def _python_supported(info: PythonInfo, system: str, apple_silicon: bool) -> bool:
    if (info.major, info.minor) < (3, 10):
        return False
    if system == "Darwin":
        if not apple_silicon:
            return False
        if info.architecture not in {"arm64", "aarch64", "arm64e"}:
            return False
    if system == "Windows":
        if (info.major, info.minor) > (3, 12):
            return False
        if info.architecture not in {"amd64", "x86_64"}:
            return False
    return True


def _select_host_python() -> PythonInfo:
    system = platform.system()
    apple_silicon = _host_is_apple_silicon()
    if system == "Darwin" and not apple_silicon:
        raise LauncherError(
            "The current MinerU/PyTorch runtime requires Apple Silicon on macOS; "
            "Intel Macs are not supported"
        )
    macos_major = _macos_major_version()
    if macos_major is not None and macos_major < 14:
        raise LauncherError("MinerU requires macOS 14 or newer")
    configured = os.environ.get("MEDAI_MINERU_PYTHON")
    candidate = _command_path(configured) if configured else Path(sys.executable).resolve()
    if candidate is None:
        raise LauncherError(f"Host Python is not available: {configured}")
    info = _python_info(candidate)
    if _python_supported(info, system, apple_silicon):
        return info
    if configured:
        raise LauncherError(
            f"Selected MinerU Python is incompatible with {system}: {info.fingerprint}"
        )

    if apple_silicon:
        native_python = Path("/opt/homebrew/opt/python@3.12/bin/python3.12")
        if not native_python.is_file():
            native_brew = Path("/opt/homebrew/bin/brew")
            if not native_brew.is_file():
                raise LauncherError(
                    "Apple Silicon requires native arm64 Python 3.10+; install native "
                    "Homebrew from https://brew.sh or set MEDAI_MINERU_PYTHON"
                )
            print("Installing native Python 3.12 with Homebrew.", flush=True)
            subprocess.run(
                _native_homebrew_install_command(
                    native_brew,
                    Path("/usr/bin/arch"),
                ),
                check=True,
            )
        info = _python_info(native_python)
        if _python_supported(info, system, apple_silicon):
            return info

    if system == "Windows" and shutil.which("py"):
        python312 = _command_output(
            ["py", "-3.12", "-c", "import sys; print(sys.executable)"]
        )
        info = _python_info(Path(python312).resolve())
        if _python_supported(info, system, apple_silicon):
            return info

    requirement = "3.10-3.12" if system == "Windows" else "3.10 or newer"
    raise LauncherError(
        f"MinerU requires a compatible native Python ({requirement}); found {info.fingerprint}"
    )


def _archive_incompatible_venv(venv: Path, fingerprint: str) -> None:
    safe_fingerprint = re.sub(r"[^A-Za-z0-9_.-]+", "-", fingerprint)
    archived = venv.with_name(f"{venv.name}.incompatible-{safe_fingerprint}")
    if archived.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        timestamped = archived.with_name(f"{archived.name}-{timestamp}")
        archived = timestamped
        suffix = 1
        while archived.exists():
            archived = timestamped.with_name(f"{timestamped.name}-{suffix}")
            suffix += 1
    print(f"Archiving incompatible host MinerU environment to: {archived}", flush=True)
    shutil.move(str(venv), str(archived))


def _model_cache(project_root: Path) -> Path:
    configured = os.environ.get("MEDAI_MODEL_CACHE")
    value = Path(configured).expanduser() if configured else project_root / ".medai" / "mineru"
    return value.resolve()


def _init(project_root: Path) -> int:
    model_source = os.environ.get("MEDAI_MINERU_MODEL_SOURCE", "auto")
    if model_source not in {"auto", "huggingface", "modelscope"}:
        raise LauncherError(
            "MEDAI_MINERU_MODEL_SOURCE must be auto, huggingface, or modelscope"
        )

    host_python = _select_host_python()
    model_cache = _model_cache(project_root)
    model_home = model_cache / "home"
    model_home.mkdir(parents=True, exist_ok=True)
    model_config = model_cache / "mineru.json"
    model_marker = model_cache / ".medai-image-id"
    venv = model_cache / ".venv"
    runtime = _runtime_commands(venv)

    if runtime.python.is_file():
        venv_info = _python_info(runtime.python)
        if venv_info.fingerprint != host_python.fingerprint:
            _archive_incompatible_venv(venv, venv_info.fingerprint)
    runtime = _runtime_commands(venv)
    pip_command = [runtime.python, "-m", "pip", "install"]
    index_url = os.environ.get("MEDAI_PYPI_INDEX")
    if index_url:
        pip_command.extend(["--index-url", index_url])

    if not runtime.python.is_file():
        print(f"Creating host MinerU environment: {venv}", flush=True)
        subprocess.run([str(host_python.executable), "-m", "venv", str(venv)], check=True)
        subprocess.run([*(str(part) for part in pip_command), "--upgrade", "pip"], check=True)

    requirements = Path(__file__).resolve().parent / "data" / "mineru-requirements.txt"
    if not requirements.is_file():
        raise LauncherError(f"Missing MinerU requirements: {requirements}")
    print("Installing host MinerU runtime.", flush=True)
    torch_index_url = os.environ.get("MEDAI_TORCH_INDEX_URL")
    if torch_index_url:
        print("Installing PyTorch from the configured device-specific index.", flush=True)
        subprocess.run(
            [
                str(runtime.python),
                "-m",
                "pip",
                "install",
                "--index-url",
                torch_index_url,
                "torch",
                "torchvision",
            ],
            check=True,
        )
    subprocess.run(
        [*(str(part) for part in pip_command), "--requirement", str(requirements)],
        check=True,
    )

    image_name = os.environ.get("MEDAI_IMAGE", "medai:local")
    docker_platform = os.environ.get("MEDAI_DOCKER_PLATFORM", "linux/amd64")
    print(f"Building MedAI image: {image_name}", flush=True)
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            docker_platform,
            "-f",
            str(project_root / "docker" / "Dockerfile"),
            "-t",
            image_name,
            str(project_root),
        ],
        check=True,
    )

    model_env = os.environ.copy()
    model_env.update(
        {
            "HOME": str(model_home),
            "HF_HOME": str(model_cache / "huggingface"),
            "MODELSCOPE_CACHE": str(model_cache / "modelscope"),
            "MINERU_TOOLS_CONFIG_JSON": str(model_config),
        }
    )
    print(f"Initializing MinerU models in: {model_cache}", flush=True)
    subprocess.run(
        [str(runtime.models_download), "--source", model_source, "--model_type", "all"],
        env=model_env,
        check=True,
    )
    if not model_config.is_file() or model_config.stat().st_size == 0:
        raise LauncherError(
            f"MinerU initialization completed without creating {model_config}"
        )
    image_id = _command_output(
        ["docker", "image", "inspect", image_name, "--format", "{{.Id}}"]
    )
    model_marker.write_text(f"host-mineru:{image_id}\n", encoding="utf-8")
    print("MedAI initialization completed.", flush=True)
    return 0


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medai",
        description="Run MedAI replication or Auto Research workflows.",
        epilog="Initialize the host runtime once with: medai init",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replicate", action="store_true")
    mode.add_argument("--autoresearch", action="store_true")
    parser.add_argument("--paper", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument(
        "--data",
        action="append",
        help="Explicitly supplied dataset name; repeat for multiple datasets",
    )
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--clouddrive", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replicate-run", type=Path)
    parser.add_argument("--provider")
    parser.add_argument("--siliconflow-config", type=Path)
    parser.add_argument("--codex-model")
    parser.add_argument("--codex-reasoning-effort")
    parser.add_argument("--smart-replicate", action="store_true")
    parser.add_argument(
        "--on-partial-data",
        choices=("ask", "continue", "stop"),
        default="continue",
    )
    parser.add_argument("--max-iter", type=int)
    parser.add_argument("--assessment-threshold", type=float)
    return parser


def _required_file(path: Path, option: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise LauncherError(f"{option} must be an existing file: {resolved}")
    return resolved


def _optional_directory(path: Optional[Path], option: str) -> Optional[Path]:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise LauncherError(f"{option} must be an existing directory: {resolved}")
    return resolved


def _new_output(runs_root: Path, paper: Path) -> Path:
    paper_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", paper.stem).strip("_") or "paper"
    prefix = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{paper_name}"
    output = runs_root / prefix
    suffix = 1
    while True:
        try:
            output.mkdir()
            return output
        except FileExistsError:
            output = runs_root / f"{prefix}_{suffix}"
            suffix += 1


def _resolve_output(requested: Optional[Path], runs_root: Path, paper: Path) -> Path:
    if requested is None:
        output = _new_output(runs_root, paper)
        print(f"Run output: {output}", flush=True)
        return output
    output = requested.expanduser().resolve()
    if not output.is_dir() or not output.is_relative_to(runs_root):
        raise LauncherError(f"--output must be an existing directory under {runs_root}")
    if not (output / "manifest.json").is_file():
        raise LauncherError(f"--output does not contain manifest.json: {output}")
    print(f"Resuming run output: {output}", flush=True)
    return output


def _resolve_base_run(requested: Optional[Path], runs_root: Path) -> Path:
    if requested is None:
        raise LauncherError("--autoresearch requires --replicate-run")
    base_run = requested.expanduser().resolve()
    if not base_run.is_dir() or not base_run.is_relative_to(runs_root):
        raise LauncherError(
            f"--replicate-run must be an existing directory under {runs_root}"
        )
    if not (base_run / "manifest.json").is_file():
        raise LauncherError(f"--replicate-run does not contain manifest.json: {base_run}")
    print(f"Auto Research base run: {base_run}", flush=True)
    return base_run


def _new_autoresearch_output(base_run: Path) -> Path:
    root = base_run / "autoresearch"
    root.mkdir(parents=True, exist_ok=True)
    indices = [
        int(match.group(1))
        for path in root.iterdir()
        if path.is_dir() and (match := re.fullmatch(r"campaign_(\d+)", path.name))
    ]
    index = max(indices, default=0) + 1
    while True:
        output = root / f"campaign_{index:03d}"
        try:
            output.mkdir()
            print(f"Auto Research output: {output}", flush=True)
            return output
        except FileExistsError:
            index += 1


def _resolve_autoresearch_output(requested: Optional[Path], base_run: Path) -> Path:
    if requested is None:
        return _new_autoresearch_output(base_run)
    output = requested.expanduser().resolve()
    if output == base_run:
        raise LauncherError(
            "Auto Research output must be separate from the read-only base run"
        )
    if output.exists() and not output.is_dir():
        raise LauncherError(f"--output must be a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        if not (output / "manifest.json").is_file():
            raise LauncherError(
                f"Auto Research output is not empty and has no manifest.json: {output}"
            )
        print(f"Resuming Auto Research output: {output}", flush=True)
    else:
        print(f"Auto Research output: {output}", flush=True)
    return output


def _detect_mineru_device(python: Path) -> str:
    device = _command_output(
        [
            python,
            "-c",
            (
                "import torch; "
                'print("cuda" if torch.cuda.is_available() else '
                '"mps" if hasattr(torch.backends, "mps") and '
                'torch.backends.mps.is_available() else "cpu")'
            ),
        ]
    ).casefold()
    if device not in {"cpu", "cuda", "mps"}:
        raise LauncherError(f"MinerU returned an unsupported device mode: {device}")
    return device


def _mount(source: Path, destination: str, readonly: bool = False) -> str:
    value = f"type=bind,src={source},dst={destination}"
    return f"{value},readonly" if readonly else value


def _run(project_root: Path, argv: Sequence[str]) -> int:
    args, forwarded = _run_parser().parse_known_args(argv)
    paper = None
    repo = None
    data: list[Path] = []
    dataset_names: list[str] = []
    cloud_datasets: list[str] = []
    base_run = None
    autoresearch_output = None
    inherited_inputs: dict[str, object] = {}
    if args.replicate:
        if args.paper is None:
            raise LauncherError("--replicate requires --paper")
        if args.max_iter is not None:
            raise LauncherError("--max-iter requires --autoresearch")
        if args.assessment_threshold is not None:
            raise LauncherError("--assessment-threshold requires --autoresearch")
        if args.replicate_run is not None:
            raise LauncherError("--replicate-run requires --autoresearch")
        paper = _required_file(args.paper, "--paper")
        if paper.suffix.casefold() != ".pdf":
            raise LauncherError(f"--paper must be a PDF: {paper}")
        repo = _optional_directory(args.repo, "--repo")
        dataset_names = [value.strip() for value in (args.data or [])]
        if any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dataset)
            or dataset in {".", ".."}
            for dataset in dataset_names
        ):
            raise LauncherError(
                "--replicate requires each --data as one safe dataset name; repeat --data for multiple datasets"
            )
        if len(set(dataset_names)) != len(dataset_names):
            raise LauncherError("--data dataset names must be unique")
        if args.dataset_path is not None and not dataset_names:
            raise LauncherError("--dataset-path requires at least one --data dataset name")
        if args.clouddrive and not dataset_names:
            raise LauncherError("--clouddrive requires at least one --data dataset name")
        if dataset_names and args.dataset_path is None and not args.clouddrive:
            raise LauncherError("--replicate requires --dataset-path, --clouddrive, or both")
        if args.clouddrive:
            cloud_datasets = list(dataset_names)
        if args.dataset_path is not None:
            dataset_root = _optional_directory(args.dataset_path, "--dataset-path")
            assert dataset_root is not None
            data = [(dataset_root / dataset).resolve() for dataset in dataset_names]
            missing = [path for path in data if not path.is_dir()]
            if missing:
                raise LauncherError(f"Local dataset directory does not exist: {missing[0]}")
        provider = (args.provider or "codex").strip().casefold()
        codex_model = args.codex_model
        codex_reasoning_effort = args.codex_reasoning_effort
        max_iter = None
        assessment_threshold = None
    else:
        if (
            args.paper is not None
            or args.repo is not None
            or args.data is not None
            or args.dataset_path is not None
            or args.clouddrive
            or args.on_partial_data != "continue"
        ):
            raise LauncherError(
                "--autoresearch does not accept --paper, --repo, --data, "
                "--dataset-path, --clouddrive, or --on-partial-data"
            )
        if args.smart_replicate:
            raise LauncherError("--smart-replicate requires --replicate")
        max_iter = args.max_iter if args.max_iter is not None else 1
        if not 1 <= max_iter <= 10:
            raise LauncherError("--max-iter must be between 1 and 10")
        assessment_threshold = (
            args.assessment_threshold if args.assessment_threshold is not None else 0.0
        )
        if not math.isfinite(assessment_threshold) or assessment_threshold < 0:
            raise LauncherError(
                "--assessment-threshold must be a finite non-negative number"
            )

        runs_root = (project_root / "runs").resolve()
        runs_root.mkdir(parents=True, exist_ok=True)
        base_run = _resolve_base_run(args.replicate_run, runs_root)
        manifest_path = base_run / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LauncherError(f"Base run manifest is not valid JSON: {manifest_path}") from exc
        inherited = manifest.get("inputs")
        if not isinstance(inherited, dict):
            raise LauncherError(f"Base run manifest has invalid inputs: {manifest_path}")
        inherited_inputs = inherited
        provider = (args.provider or str(inherited_inputs.get("provider", ""))).strip().casefold()
        if not provider:
            raise LauncherError("Base run does not record a provider; pass --provider")
        if provider == "codex":
            codex_model = args.codex_model or inherited_inputs.get("codex_model")
            codex_reasoning_effort = (
                args.codex_reasoning_effort
                or inherited_inputs.get("codex_reasoning_effort")
            )
        else:
            codex_model = args.codex_model
            codex_reasoning_effort = args.codex_reasoning_effort

        data_sources = inherited_inputs.get("data_sources")
        if isinstance(data_sources, list) and data_sources:
            dataset_names = [
                str(value)
                for value in inherited_inputs.get("datasets", [])
                if isinstance(value, str)
            ]
            if len(dataset_names) != len(data_sources):
                raise LauncherError("Base run records inconsistent local dataset sources")
            data = [
                _optional_directory(Path(str(source)), "base run data")
                for source in data_sources
            ]
            data = [path for path in data if path is not None]
        elif (data_source := inherited_inputs.get("data_source")):
            resolved_data = _optional_directory(Path(str(data_source)), "base run data")
            if resolved_data is not None:
                data = [resolved_data]
                dataset_names = [resolved_data.name]
        elif inherited_inputs.get("data"):
            raise LauncherError(
                "Base run uses local data but does not record its host source path"
            )

    if provider not in {"claude", "codex", "codex-siliconflow"}:
        raise LauncherError(f"Unsupported provider: {provider}")
    siliconflow_config = None
    if args.siliconflow_config:
        siliconflow_config = _required_file(args.siliconflow_config, "--siliconflow-config")
    if provider == "codex-siliconflow" and siliconflow_config is None:
        raise LauncherError("codex-siliconflow requires --siliconflow-config")
    if provider != "codex-siliconflow" and siliconflow_config is not None:
        raise LauncherError("--siliconflow-config requires --provider codex-siliconflow")
    if provider != "codex" and (codex_model or codex_reasoning_effort):
        raise LauncherError("Codex model settings require --provider codex")

    image_name = os.environ.get("MEDAI_IMAGE", "medai:local")
    docker_platform = os.environ.get("MEDAI_DOCKER_PLATFORM", "linux/amd64")
    model_cache = _model_cache(project_root)
    model_config = model_cache / "mineru.json"
    model_marker = model_cache / ".medai-image-id"
    runtime = _runtime_commands(model_cache / ".venv")
    if not runtime.mineru.is_file():
        raise LauncherError("Host MinerU environment is not initialized; run medai init first")
    if not model_config.is_file() or not model_marker.is_file():
        raise LauncherError("MinerU models are not initialized; run medai init first")
    try:
        image_id = _command_output(
            ["docker", "image", "inspect", image_name, "--format", "{{.Id}}"]
        )
    except subprocess.CalledProcessError as exc:
        raise LauncherError("MedAI image is not initialized; run medai init first") from exc
    if model_marker.read_text(encoding="utf-8").strip() != f"host-mineru:{image_id}":
        raise LauncherError(
            "MedAI image or host MinerU initialization changed; run medai init again"
        )

    runs_root = (project_root / "runs").resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    if args.replicate:
        assert paper is not None
        output = _resolve_output(args.output, runs_root, paper)
    else:
        assert base_run is not None
        autoresearch_output = _resolve_autoresearch_output(args.output, base_run)
        output = autoresearch_output

    with ExitStack() as stack:
        mineru_output = None
        if args.replicate and (
            not (output / "preprocessing" / "paper.md").is_file()
            or not (output / "preprocessing" / "artifacts").is_dir()
        ):
            assert paper is not None
            mineru_output = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="medai-mineru-"))
            )
            device = _detect_mineru_device(runtime.python)
            backend = os.environ.get("MEDAI_MINERU_BACKEND", "pipeline")
            mineru_env = os.environ.copy()
            mineru_env.update(
                {
                    "HOME": str(model_cache / "home"),
                    "HF_HOME": str(model_cache / "huggingface"),
                    "MODELSCOPE_CACHE": str(model_cache / "modelscope"),
                    "MINERU_MODEL_SOURCE": "local",
                    "MINERU_TOOLS_CONFIG_JSON": str(model_config),
                }
            )
            mineru_env.setdefault("MINERU_DEVICE_MODE", device)
            mineru_command = [
                str(runtime.mineru),
                "-p",
                str(paper),
                "-o",
                str(mineru_output),
            ]
            mineru_command.extend(["-b", backend])
            print(f"Running MinerU natively on the host ({device}).", flush=True)
            subprocess.run(mineru_command, env=mineru_env, check=True)

        docker_args = [
            "docker",
            "run",
            "--rm",
            "--platform",
            docker_platform,
        ]
        if args.replicate:
            assert paper is not None
            docker_args.extend(
                [
                    "--env",
                    f"MEDAI_HOST_PAPER={paper}",
                    "--mount",
                    _mount(paper, "/workspace/inputs/paper.pdf", readonly=True),
                    "--mount",
                    _mount(output, "/workspace/output"),
                ]
            )
            cli_args = [
                "--replicate",
                "--paper",
                "/workspace/inputs/paper.pdf",
                "--provider",
                provider,
                "--output",
                "/workspace/output",
                "--on-partial-data",
                args.on_partial_data,
            ]
            if mineru_output:
                docker_args.extend(
                    [
                        "--env",
                        "MEDAI_MINERU_OUTPUT=/workspace/mineru-output",
                        "--mount",
                        _mount(mineru_output, "/workspace/mineru-output", readonly=True),
                    ]
                )
            if repo:
                docker_args.extend(
                    [
                        "--env",
                        f"MEDAI_HOST_REPO={repo}",
                        "--mount",
                        _mount(repo, "/workspace/repo", readonly=True),
                    ]
                )
                cli_args.extend(["--repo", "/workspace/repo"])
        else:
            assert base_run is not None
            assert autoresearch_output is not None
            docker_args.extend(
                [
                    "--env",
                    f"MEDAI_HOST_BASE_RUN={base_run}",
                    "--mount",
                    _mount(base_run, "/workspace/base-run", readonly=True),
                    "--mount",
                    _mount(autoresearch_output, "/workspace/autoresearch"),
                ]
            )
            cli_args = [
                "--autoresearch",
                "--replicate-run",
                "/workspace/base-run",
                "--provider",
                provider,
                "--output",
                "/workspace/autoresearch",
                "--max-iter",
                str(max_iter),
                "--assessment-threshold",
                str(assessment_threshold),
            ]
        if data:
            host_sources = [str(path) for path in data]
            docker_args.extend(
                [
                    "--env",
                    f"MEDAI_HOST_DATA_SOURCES={json.dumps(host_sources)}",
                ]
            )
            if len(data) == 1:
                docker_args.extend(["--env", f"MEDAI_HOST_DATA={data[0]}"])
            for dataset_name, path in zip(dataset_names, data, strict=True):
                container_path = (
                    "/workspace/data"
                    if len(data) == 1
                    else f"/workspace/data/{dataset_name}"
                )
                docker_args.extend(
                    ["--mount", _mount(path, container_path, readonly=True)]
                )
                if args.replicate:
                    cli_args.extend(
                        ["--data", container_path, "--dataset-name", dataset_name]
                    )
        if cloud_datasets:
            cli_args.append("--clouddrive")
            for cloud_dataset in cloud_datasets:
                cli_args.extend(
                    ["--cloud-dataset" if data else "--data", cloud_dataset]
                )
        if siliconflow_config:
            docker_args.extend(
                [
                    "--mount",
                    _mount(
                        siliconflow_config,
                        "/run/secrets/siliconflow.env",
                        readonly=True,
                    ),
                ]
            )
            cli_args.extend(["--siliconflow-config", "/run/secrets/siliconflow.env"])
        if codex_model:
            cli_args.extend(["--codex-model", str(codex_model)])
        if codex_reasoning_effort:
            cli_args.extend(["--codex-reasoning-effort", str(codex_reasoning_effort)])
        if args.replicate and args.smart_replicate:
            cli_args.append("--smart-replicate")

        home = Path.home()
        for name in ("codex", "claude", "ssh"):
            credentials = home / f".{name}"
            if credentials.is_dir():
                docker_args.extend(
                    [
                        "--mount",
                        _mount(credentials, f"/credentials/{name}", readonly=True),
                    ]
                )
        env_file = project_root / ".env"
        if env_file.is_file():
            docker_args.extend(["--env-file", str(env_file)])
        if shutil.which("nvidia-smi"):
            docker_args.extend(["--gpus", "all"])
        if sys.stdin.isatty():
            docker_args.append("-i")
        subprocess.run([*docker_args, image_name, *cli_args, *forwarded], check=True)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        project_root = _project_root()
        if arguments[:1] == ["init"]:
            if len(arguments) != 1:
                raise LauncherError("medai init does not accept additional arguments")
            return _init(project_root)
        return _run(project_root, arguments)
    except LauncherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"ERROR: Required command is not available: {exc.filename}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        if exc.returncode in {3, 4}:
            return exc.returncode
        command = " ".join(str(part) for part in exc.cmd)
        print(f"ERROR: Command failed with exit code {exc.returncode}: {command}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
