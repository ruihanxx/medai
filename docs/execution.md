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
`MEDAI_MINERU_BACKEND` may override it. Replicate requires `--paper`,
`--provider`; `--repo` is an optional extra/fallback calibration source, never
codegen input. Repeat `--data` for each explicitly supplied
dataset (for example `--data mimic-iv --data eicu`). Each
value is a unique safe directory name and rejects slashes, absolute paths, `.`
and `..`. Data may be omitted so the paper audit can identify unsupplied
requirements; every explicitly selected local path must still exist. With `--dataset-path`, the
launcher requires every `<dataset-path>/<data>` directory to exist and mounts
only the selected directories read-only. A single selection retains the
legacy `/workspace/data` mount; multiple selections use
`/workspace/data/<data>` children. With
`--clouddrive` alone, no host data directory is mounted and the provider
materializes every `medai/<data>` cloud source onto its distinct remote target
before inspection. Both selectors may be supplied: local execution uses all
selected mounted datasets, while resource-insufficient remote execution uses
all selected cloud datasets instead of uploading local copies. A
missing explicitly selected local dataset is an error and never falls back to
a billable cloud source.
When a selected drive opts into cloud-pull handoff and the provider is direct
Codex, data availability performs read-only resource selection but returns each
state-changing create and materialization operation and every remote source
inspection as one foreground command. Orchestration runs it without an active
Codex process, records its terminal result, and resumes the same session. The
agent rereads canonical provider state after every resume and may inspect cloud
data only after completed materialization. Codegen returns every
cloud-materialization action required after its own reconciliation for the same
foreground orchestration handoff. Auto Research retains its local-monitor
handoff.
Direct-Codex base replication likewise hands each experiment to orchestration
as one foreground local command, including adapter invocation for remote work.
The request includes a positive hard timeout, a compact read-only progress
command, and an exact graceful-stop command. On timeout orchestration runs the
graceful stop, settles the local process group, captures lightweight progress,
updates a compact current-handoff JSON that points to the immutable result and
logs, and uses only that JSON to resume the agent. After six terminal handoffs it
starts a fresh thread from the complete replication prompt, refreshed canonical
node state, and latest handoff pointer. The same rollover handles the dedicated
`context_exhausted` agent result; a second consecutive context result without an
intervening terminal experiment is terminal. Timeout alone is not a terminal
workflow failure and does not release the instance.
Provider-specific resource selection, create initialization, fallback, and
retry behavior lives only in the metadata-selected computation-provider
reference. A provider create is successful only after its documented remote
readiness check, including SSH authentication when applicable. An unambiguously
owned instance that fails create readiness is recorded as a failed creation so
it can be released before a bounded replacement; host orchestration never
infers an undocumented alternative.

The data-availability agent receives the complete preflight CPU,
available-memory, free-disk, and GPU snapshot. It first determines whether
faithful full-scale execution needs a
GPU, then inventories the selected local dataset's release/version, actual size,
files, partitions, formats, and available row-count metadata before judging
capacity. Paper-stated hardware remains distinct from inferred capacity. For
CPU-only work with no stated hardware, eight physical cores are sufficient by
default and data size alone cannot justify a higher floor; only an explicit
parallel-method requirement or a representative benchmark showing the complete
run exceeds the 12-hour limit can do so. Memory is judged from the planned
streaming, chunked, or out-of-core implementation and requires 20% headroom over
estimated or measured peak use. With dataset size `D` and unknown peak writable
work files, remote disk defaults to `D + max(D, 10 GiB)`, while a local run over
read-only source data requires additional free space of `max(D, 10 GiB)` at the
actual work/output landing point. Uncertainty requires a bounded capacity probe
and never itself authorizes remote execution; an unresolved probe marks the
affected claim paths as unknown. Other runnable claim paths still proceed as a
partial replication; the run stops only when no claim remains runnable.
A configured provider is only a fallback: sufficient local resources prohibit
offer search, instance creation, and remote state. Demonstrated insufficiency
uses the selected provider's documented GPU or CPU-only procedure; absence of a
provider or of a provider-specific CPU-only procedure fails availability without
reducing the required scientific scale. `--clouddrive` alone remains remote regardless of
local capacity because raw data has no local path; when local data is also
supplied, the normal local-first capacity decision applies. Codegen consumes
this persisted location decision and may not repeat or change it.
`--force-remote` overrides the local-first capacity choice for replication and
requires every runnable scope to use the configured computation provider even
when local resources are sufficient. It requires a configured computation
provider, remains subject to the same full-scale capacity floors and partial-data
gate, and is recorded in `manifest.json`. For local-only data, Availability makes
the binding remote decision without renting or uploading; Codegen realizes it
after the gate. Auto Research does not accept this replication-only flag.

Replication accepts `--on-partial-data continue|ask|stop` (default `continue`).
A PARTIAL run lists reproducible and blocked claims, their node paths, direct
blockers, and dependency chains, records the scope-bound decision, and proceeds
with the runnable claim subgraph by default when it uses at least one confirmed
source. A scope with no active source stops instead of executing claims that can
be derived entirely without an available dataset. Explicit interactive `ask`
prompts `Continue with the runnable claim subgraph? [y/N]`.
Non-interactive `ask` safely powers off and exits 3 with resume instructions;
`stop` exits 4, records `stopped_by_user`, and releases run-owned compute. A
decision is valid for one scope hash only.
For local-only data, Availability may select remote execution but cannot search
offers, rent, or upload before the gate; Codegen realizes that approved decision
after confirmation and transfers only runnable-scope data. Cloud-only and
dual-source remote scopes are materialized and audited by Availability itself.

Auto Research requires `--replicate-run runs/<run_id>` and accepts an optional
campaign `--output`. Without `--output`, the launcher atomically creates the
next directory under `runs/<run_id>/autoresearch/campaign_NNN`, using one-based
zero-padded monotonically increasing numbers. An explicit output path that does
not exist or is empty starts a campaign there; an explicit non-empty output
resumes only when it contains `manifest.json`. Auto Research accepts
`--max-iter` from 1 through 10 (default 1),
accepts a non-negative `--assessment-threshold` for the weighted -5-through-5
idea-assessment score (default `0.0`), and rejects `--paper`, `--repo`, `--data`,
and `--smart-replicate`. A cloud-backed campaign inherits the base run's
computation provider, drive, dataset, and source. It requires the base instance
to be released and its completed cloud inventory to remain reloadable; the
campaign owns a separate instance and copies the inventory as its immutable
materialization baseline.
Supported providers are `claude`, `codex`, and `codex-siliconflow`.
The SiliconFlow dotenv may set `CODEX_CLI_SILICONFLOW_REASONING_EFFORT` to
`high` or `max`; the adapter forwards it unchanged as the SiliconFlow
`chat/completions` `reasoning_effort` field. Blank or omitted leaves the field
unset for models that do not support it.
Paper, optional local repository, data, provider configuration, and CLI
credentials are mounted read-only. Preflight snapshots a local repository and
deduplicates it with paper-disclosed sources. The host `~/.ssh` directory is
copied from its read-only
mount into the container's ephemeral HOME so computation-provider SSH operations
can use OpenSSH config and identities without modifying host credentials. The
project `.env` is passed to Docker with `--env-file`, so provider skills must
tolerate Docker's literal preservation of optional surrounding quotes in
credential values. The file itself is not mounted into an agent stage working
directory: provider adapters read the inherited process environment, and an
absent stage-local `.env` is not a configuration failure. A new replication
invocation creates a unique run directory under the repository-root `runs/`
directory, named from its UTC start time and paper filename. Passing its existing
directory through replication `--output` resumes it.

Auto Research restores paper, repository, and data locations from the base
manifest, skips MinerU, and requires manifest v7 plus a completed base run with
all canonical replication stages reloadable. Manifest v1–v6 is rejected before
writeback. The launcher mounts the base run
read-only at `/workspace/base-run`, mounts only the selected campaign output
writable at `/workspace/autoresearch`, and remounts recorded local source data
read-only. Cloud-only campaigns mount no host data directory; dual-source
campaigns retain the local read-only mount. A missing recorded local source data
path is an explicit error. The campaign inherits the base agent
provider, model, reasoning effort, and remote provider/drive selection unless an
allowed CLI value overrides the agent field. `codex-siliconflow` still requires
a newly supplied secret configuration. Multiple campaigns may share one
read-only base run; each has an independent manifest, artifacts, and remote
state. Resuming one requires an explicit `--output` plus the same base
fingerprint and resolved configuration.

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

Remote-compute secrets and local adapter configuration come only from the
environment. New replicate runs may select with `MEDAI_COMPUTATION_PROVIDER`
and, for `--clouddrive`, `MEDAI_DRIVE_PROVIDER`.
When these selectors are omitted, MedAI uses the recorded resume selection or
the cloud-backed Auto Research base selection, then exactly one fully configured
adapter. The selected computation-provider skill metadata defines its required
variables, defaults, supported drives, source mapping, action timeouts, and
non-secret configuration fingerprint. Secrets are never placed in manifests,
command arguments, prompts, or logs.

Every terminal Replicate or Auto Research outcome attempts power-off and release
of each unambiguously run-owned instance before the CLI exits, including early
NONE scope, explicit stop, and failure before report completion. The resumable
non-interactive partial-data confirmation pause is not terminal and powers off
without release. Cleanup failures are appended to the primary terminal error so
they never replace it. On explicit resume the CLI reconciles canonical state
before entering LangGraph and may create one bounded replacement from recorded
actual specifications. Ambiguous provider failures or an unsuccessful
old-instance release prevent a second rental. A replacement before replication
invalidates codegen and downstream work as an infrastructure resume. Once
replication has begun, explicit resume snapshots the attempt, recovers valid
node artifacts, and reruns only nodes that fail result, evidence, generic
integrity, or predecessor-closure checks. Cloud data is materialized
idempotently before resumed replication execution. A cleanup failure after
successful completion is a persistent `cleanup_warning`, not a pipeline
failure, and reopening that completed run does not retry it.

For cloud-backed Auto Research, host orchestration owns pool selection and
preparation, provider execution, artifact validation, reconciliation,
power-off, and release. It powers the pool off before resuming an agent and
releases owned members on every terminal outcome. The campaign state machine
and data-materialization flow are defined in `autoresearch.md`; agent-facing
operation and transfer permissions are defined in `agents.md`.

`--smart-replicate` is disabled by default. When enabled, the replicate agent
receives the audited `paper_result` anchors for its assigned claims, performs a
baseline run, and may make at most five hypothesis-driven adjustment rounds per
claim. Each round must compare actual output with its anchor, record a
methodological hypothesis and exact change, and rerun the affected commands.
Hard-coding anchors, editing computed outputs, or unsupported tuning remains
prohibited. The resolved boolean is recorded in `manifest.json`.

After PDF conversion, preflight extracts only verbatim paper-disclosed public
HTTPS Git URLs. Git acquisition is non-interactive, disables hooks and LFS
smudge, pins the URL ref or fetched default-branch commit, recursively accepts
only similarly valid submodules, removes `.git`, and records missing LFS or
submodule content. Failures remain in the inventory and replication continues.
Completed preflight inventories are frozen: resume hash-checks snapshots and
never downloads or updates them. Codegen receives none of these sources;
calibration statically reads the frozen snapshots only after independent
codegen. Remote synchronization contains calibrated generated code only.
