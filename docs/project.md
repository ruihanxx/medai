# Project Contract

## CLI and isolation

The cross-platform host launcher is implemented in `medai.launcher`; `./medai`
is its thin Linux/macOS wrapper and `medai.cmd` is its Windows wrapper. It runs
from a source checkout because initialization builds the local Docker overlay
from that checkout. `medai init` performs all shared initialization: it creates
a dedicated host Python environment, validates Python 3.10+ (3.10-3.12 on
Windows), requires macOS 14+ on arm64 Apple Silicon and x86_64 on Windows,
installs the pinned MinerU runtime from
`src/medai/data/mineru-requirements.txt`, builds `medai:local`, downloads all
MinerU pipeline and VLM models, and records the initialized image ID. The
environment and models are stored under
`.medai/mineru/` by default; `MEDAI_MODEL_CACHE`
may select another host directory and `MEDAI_MINERU_MODEL_SOURCE` may select
`auto`, `huggingface`, or `modelscope`. `MEDAI_MINERU_PYTHON` may select the
host Python used to create the environment, `MEDAI_PYPI_INDEX` selects its
general package index, and `MEDAI_TORCH_INDEX_URL` optionally selects a
device-specific PyTorch index. When no Python is explicitly selected on Apple
Silicon, initialization uses or installs native Homebrew Python 3.12. If an
existing environment differs from the selected interpreter's version or
architecture, initialization archives it beside the replacement environment.
Initialization is otherwise idempotent because completed environments and
model downloads are reused.

Normal `./medai` runs never build an image or download models. They require the
current image ID and host model cache to match the last successful
initialization and fail with an instruction to run `./medai init` when either
is missing or stale. Every run selects exactly one of `--replicate` and
`--autoresearch`. Before starting a replicate run whose PDF stage is incomplete,
the launcher invokes the host `mineru` command and mounts its temporary output
read-only into the container. It detects CUDA, Apple MPS, or CPU from PyTorch,
sets `MINERU_DEVICE_MODE`, and defaults to the cross-platform `pipeline` backend;
`MEDAI_MINERU_BACKEND` may override it. Replicate requires `--paper` and
`--provider`; `--repo` and `--data` are optional. Auto Research requires
`--output runs/<run_id>`, accepts `--max-iter` from 1 through 10 (default 1),
and rejects `--paper`, `--repo`, `--data`, and `--smart-replicate`.
Supported providers are `claude`, `codex`, and `codex-siliconflow`.
Paper, repository, data, provider configuration, and CLI credentials are
mounted read-only. A new invocation creates a unique run directory under the
repository-root `runs/` directory, named from its UTC start time and paper
filename. Passing `--output runs/<run_id>` mounts that existing directory and
resumes it.

Auto Research restores paper, repository, and data locations from the base
manifest, skips MinerU, and requires the base run to be completed with all seven
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

## Workflow

The LangGraph stages are:

1. `preflight`: validate inputs and record CPU, RAM, disk, and GPU resources.
2. `preprocess_pdf`: import the host MinerU result, convert it to canonical
   Markdown, and copy images. Host MinerU output remains temporary; only the
   canonical Markdown and artifacts persist in the run directory.
3. `preprocessing_agent`: write text/numeric claims and experiment definitions.
4. `codegen_agent`: inspect supplied data directly through bounded, read-only,
   non-executing reads, compare local GPU capacity with the paper's full-scale
   requirements, use the
   `computation-provider` skill to rent matching configured remote compute when
   needed, plan files, and write code.
5. `plan_agent`: check coverage, install dependencies, smoke-test, and write the replication plan.
6. `replicate_agent`: execute every experiment and write evidence.
7. `report_agents`: sequentially update one report with per-experiment
   claim/artifact comparisons, validation-anchor assessments, and a risk list
   derived from code-generation ambiguities.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent failure stops the run explicitly.

`manifest.json` is the canonical pipeline state. It records a versioned input
fingerprint, overall and per-stage status, attempts, timestamps, outputs, and
stage checkpoints. On reuse of an output directory, version 1 manifests are
migrated, the paper hash and output-affecting configuration must match, and
only stages marked `completed` are skipped. Every skipped stage reloads and
validates its canonical artifacts before downstream work proceeds. A
`running` or `failed` stage starts another attempt while retaining its writable
artifacts. Failure handling reloads the current manifest before recording the
error so stage updates are not overwritten by stale state. Code generation
records source preparation before invoking its agent; replication continues
from the valid ordered prefix in its step log; report generation checkpoints
every completed experiment. A completed run is therefore safe to invoke again
and becomes a validation-only no-op.

### Auto Research workflow

Auto Research has its own manifest, checkpoints, and dynamic stages below the
base run. Preflight records hardware resources and fingerprints the canonical
base artifacts and codebase. It also requires
`templates/skills/idea-generation/SKILL.md`; this repository contract does not
provide that skill, so absence fails before agent execution. A separate
eligibility agent admits only supervised machine-learning tasks with a defined
prediction target. An ineligible campaign writes its decision, records status
`ineligible`, and stops.

Each round generates exactly three ideas. Every idea has Description,
Motivation, and Provenance and receives an independent copy of the completed
replicate codebase. The copies exclude Git metadata, virtual environments, and
caches; changes never accumulate across ideas or flow back to the base run.
Each idea then proceeds sequentially through codegen, audit, plan, experiment,
and assessment. Codegen preserves the original baseline and writes a structured
implementation plan. An independent audit checks exactly four anchors: task and
prediction target, dataset/cohort/input-output definitions, metrics and
protocol, and baseline preservation. One failed audit permits one repair and
re-audit; a second failure deterministically creates an invalid assessment and
skips plan and experiment.

The Auto Research plan reuses `ReplicationPlan` without replicate claim-coverage
validation. Experiment reuses `ReplicationLog` and `EvidenceSummary`, executes
only the refinement, and compares against baseline evidence from the base run.
Assessment is `valid`, `invalid`, or `inconclusive`. When uncertainty is
available, improvement must exceed the recorded noise threshold; without base
uncertainty, any numeric improvement in the declared metric direction can be
valid. The program derives each round summary from the three assessments. All
three ideas finish before routing: any valid idea ends iteration, otherwise a
new round begins until `max_iter` is reached. Later rounds receive the prior
ideas, audit/assessment verdicts, and failure-reason paths.

Dynamic stages are named `round_001.idea_01.<stage>`. Completed stages are
skipped only after their artifacts reload and validate; retries retain provider
transcripts. The campaign manifest records the base fingerprint, resolved
provider configuration, maximum iterations, attempts, checkpoints, and one of
`running`, `completed`, `failed`, or `ineligible`. Final reporting includes
every candidate, including skipped, failed, and inconclusive ideas. Multiple
valid ideas are shown side by side without ranking, merging, or modifying the
base codebase. Two deterministic PNGs show baseline/refinement metrics and the
round-by-idea verdict grid, with missing results displayed as N/A.

## Persistent artifacts

```text
runs/<run_id>/
├── manifest.json  # canonical pipeline state and input fingerprint
├── preflight/resources.json
├── preprocessing/paper.md
├── preprocessing/artifacts/
├── preprocessing/claims.json
├── preprocessing/experiment_todo.json
├── preprocessing/preprocessing_transcript.jsonl
├── codegen/codebase/codegen_plan.json
├── codegen/codegen_transcript.jsonl
├── plan/replicate_plan.json
├── plan/plan_transcript.jsonl
├── replication/replication_log.json
├── replication/evidence_summary.json
├── replication/<experiment_id>/smart_replicate_log.json  # smart mode only
├── replication/replication_transcript.jsonl
├── report/reproduction_report.md
├── report/<experiment_id>_transcript.jsonl
├── prompts/
├── system_maintenance/dataset/patch.json
└── remote_compute/instance.json
```

Auto Research adds this isolated subtree to a completed base run:

```text
runs/<run_id>/autoresearch/
├── manifest.json
├── preflight/resources.json
├── eligibility/eligibility.json
├── rounds/round_001/
│   ├── ideas.md
│   ├── idea_generation_transcript.jsonl
│   ├── ideas/idea_01/
│   │   ├── codegen/codebase/
│   │   ├── codegen/implementation_plan.json
│   │   ├── audit/audit.json
│   │   ├── plan/experiment_plan.json
│   │   ├── experiment/experiment_log.json
│   │   ├── experiment/evidence_summary.json
│   │   └── assessment/assessment.json
│   └── round_summary.json
├── report/auto_research_report.md
├── report/idea_metric_comparison.png
├── report/idea_status_overview.png
├── prompts/
└── remote_compute/instance.json
```

Claims have unique `claim_id` values, are limited to `text` or `numeric`, and
record a `final` or `validation` role plus a verbatim provenance quote.
Experiments have unique `experiment_id` values and list their claim IDs and
paper artifact labels. The replication plan uses ordered steps whose
`verifies` lists collectively cover those claim IDs and artifact labels. The
replication log covers the plan steps in order, and every result-producing
step names real output files inside the copied codebase or replication
directory. The evidence summary records the execution environment. Its core
environment fields record Python, GPU availability/model, and key package
versions; additional environment metadata is accepted for auditability. The
reproduction report contains exactly three top-level audit
sections: per-experiment claim/artifact comparisons, a verdict for every
validation anchor, and one replication risk for every `codegen_plan.json`
ambiguity.

Each run initializes `system_maintenance/dataset/patch.json` as an empty JSON
array. When code generation naturally encounters an omission in a dataset
document, it may add an object containing exactly `"file name"` and
`"patch_content"`; it does not proactively search for omissions or modify the
read-only source dataset. The patch content follows the target document's
structure and remains a reviewable run artifact rather than being applied
automatically.

## Agent boundaries

- Replicate prompts live under `templates/<stage>/`; Auto Research prompts live
  under `templates/autoresearch/<stage>/`; runtime skills live under
  `templates/skills/`. None is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
- Each agent invocation's provider event stream is preserved as a JSONL
  transcript beside that stage's artifacts. Before a retried invocation, an
  existing transcript is preserved as `<name>.attempt-<N>.jsonl`. Transcript
  files are diagnostic records and are never used as the agent's structured
  result.
- Replication agents do not receive paper target values by default. Smart
  Replicate exposes only claim-level audited anchors and requires the baseline,
  comparisons, hypotheses, changes, commands, and actual round results in
  `smart_replicate_log.json`; it does not expose the paper itself.
- Plan agents may modify the writable codebase but may not change model
  semantics, introduce fallback plans, or hardcode paper results.
- Remote compute access is exposed through the `computation-provider` skill;
  its first supported provider is AutoDL. Only instances created by the current
  run may be automatically powered off or released. After replication finishes
  and required outputs are transferred, the replicate stage must release them;
  host cleanup retries release on failure paths. The generic
  `remote_compute/instance.json` records the selected provider and common
  lifecycle state; each provider reference defines its provider-specific state.

## Acceptance

Run `pytest`, `ruff check .`, `python -m medai --help`, and
`python -m medai.cli --help`. Tests mock provider, MinerU, AutoDL, and SSH
boundaries; tests never rent hardware.
