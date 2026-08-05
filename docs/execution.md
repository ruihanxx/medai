# Execution and Isolation Contract

The cross-platform host launcher is implemented in `medai.launcher`; `./medai`
is its thin Linux/macOS wrapper and `medai.cmd` is its Windows wrapper. It runs
from a source checkout because initialization builds the local Docker overlay
from that checkout. `medai init` performs all shared initialization: it creates
a dedicated host Python environment, validates Python 3.10+ (3.10-3.12 on
Windows), requires macOS 14+ on arm64 Apple Silicon and x86_64 on Windows,
installs the pinned MinerU runtime from
`src/medai/data/mineru-requirements.txt`, builds `medai:local`, downloads all
MinerU pipeline and VLM models, and records the initialized image ID. The
environment and models are stored under `.medai/mineru/` by default;
`MEDAI_MODEL_CACHE` may select another host directory and
`MEDAI_MINERU_MODEL_SOURCE` may select `auto`, `huggingface`, or `modelscope`.
`MEDAI_MINERU_PYTHON` may select the host Python used to create the environment,
`MEDAI_PYPI_INDEX` selects its general package index, and
`MEDAI_TORCH_INDEX_URL` optionally selects a device-specific PyTorch index. When
no Python is explicitly selected on Apple Silicon, initialization uses or
installs native Homebrew Python 3.12. If an existing environment differs from
the selected interpreter's version or architecture, initialization archives it
beside the replacement environment. Initialization is otherwise idempotent
because completed environments and model downloads are reused.

Normal `./medai` runs never build an image or download models. They require the
current image ID and host model cache to match the last successful
initialization and fail with an instruction to run `./medai init` when either
is missing or stale. Every run selects exactly one of `--replicate` and
`--autoresearch`. Before starting a replicate run whose PDF stage is incomplete,
the launcher invokes the host `mineru` command and mounts its temporary output
read-only into the container. It detects CUDA, Apple MPS, or CPU from PyTorch,
sets `MINERU_DEVICE_MODE`, and defaults to the cross-platform `pipeline` backend;
`MEDAI_MINERU_BACKEND` may override it. Replicate requires `--paper` and
`--provider`, and `--data`; `--repo` is optional. The CLI accepts a missing
`--data` long enough to create the run manifest, then fails the started
`preflight` stage explicitly so the failed run remains inspectable. Auto
Research requires `--output runs/<run_id>`, accepts `--max-iter` from 1 through
10 (default 1),
accepts a non-negative `--assessment-threshold` for the weighted relative
improvement score (default `0.0`), and rejects `--paper`, `--repo`, `--data`,
and `--smart-replicate`.
Supported providers are `claude`, `codex`, and `codex-siliconflow`.
Paper, repository, data, provider configuration, and CLI credentials are
mounted read-only. The host `~/.ssh` directory is copied from its read-only
mount into the container's ephemeral HOME so computation-provider SSH operations
can use OpenSSH config and identities without modifying host credentials. The
project `.env` is passed to Docker with `--env-file`, so provider skills must tolerate
Docker's literal preservation of optional surrounding quotes in credential
values. A new invocation creates a unique run
directory under the repository-root `runs/` directory, named from its UTC start
time and paper filename. Passing `--output runs/<run_id>` mounts that existing
directory and resumes it.

Auto Research restores paper, repository, and data locations from the base
manifest, skips MinerU, and requires the base run to be completed with all eight
canonical replicate stages reloadable. The launcher mounts the base run
read-only at `/workspace/base-run`, mounts only its `autoresearch/` child
writable at `/workspace/autoresearch`, and remounts the recorded source data
read-only. A missing source data path is an explicit error. The campaign
inherits the base provider, model, and reasoning effort unless a CLI value
overrides that field. `codex-siliconflow` still requires a newly supplied secret
configuration. Initial implementation permits one campaign per base run;
reusing it requires the same base fingerprint and resolved configuration.

The local `medai:local` image is a thin overlay on the canonical Veritas image
`ghcr.io/chicagohai/veritas:latest` (configurable with the Docker build argument
`VERITAS_IMAGE`). It reuses the Veritas CUDA and scientific runtime while
installing MedAI into an isolated `/opt/medai/.venv` and replacing only the
container entrypoint. The Veritas image and its `/app/.venv` remain unchanged.
The overlay also installs a shared, version-pinned R analysis layer:
`duckdb 1.5.5`, `mice 3.19.0`, `rms 8.1-1`, and `comorbidity 1.1.0`.
This layer is built once during `medai init` rather than compiled in each run.
The `VERITAS_PLATFORM` build argument and host launcher both default to
`linux/amd64`, matching the platform published by Veritas and used by the
Desktop Veritas launcher; `MEDAI_DOCKER_PLATFORM` may override the host Docker
selection when a compatible base image is available.
Dependency installation uses PyPI by default; `MEDAI_PYPI_INDEX` may select a
compatible package index at build time without changing the resulting runtime
configuration. Each overlay build explicitly refreshes the local MedAI package
so source changes cannot reuse a stale cached wheel. MinerU is a host dependency
and is not installed into the MedAI overlay environment.

The `codex` provider accepts `--codex-model` and
`--codex-reasoning-effort`. When omitted, these values come from
`MEDAI_CODEX_MODEL` and `MEDAI_CODEX_REASONING_EFFORT` in the project `.env`.
The resolved values are recorded in `manifest.json`.

`--smart-replicate` is disabled by default. When enabled, the replicate agent
receives the audited `paper_result` anchors for its assigned claims, performs a
baseline run, and may make at most five hypothesis-driven adjustment rounds per
experiment. Each round must compare actual output with its anchor, record a
methodological hypothesis and exact change, and rerun the affected commands.
Hard-coding anchors, editing computed outputs, or unsupported tuning remains
prohibited. The resolved boolean is recorded in `manifest.json`.

When a repository is supplied, it is copied to `codegen/codebase/`; agents
modify only that copy.
