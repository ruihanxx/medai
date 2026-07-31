# Project Contract

## CLI and isolation

`./medai` requires `--paper` and `--provider`; `--repo` and `--data` are
optional. Supported providers are `claude`, `codex`, and `codex-siliconflow`.
Paper, repository, data, provider configuration, and CLI credentials are
mounted read-only. Each invocation creates a unique run directory under the
repository-root `runs/` directory, named from its UTC start time and paper
filename. That run directory is the only writable host path mounted into the
container.

The `codex` provider accepts `--codex-model` and
`--codex-reasoning-effort`. When omitted, these values come from
`MEDAI_CODEX_MODEL` and `MEDAI_CODEX_REASONING_EFFORT` in the project `.env`.
The resolved values are recorded in `manifest.json`.

When a repository is supplied, it is copied to `codegen/codebase/`; agents
modify only that copy.

## Workflow

The LangGraph stages are:

1. `preflight`: validate inputs and record CPU, RAM, disk, and GPU resources.
2. `preprocess_pdf`: convert the PDF to Markdown and copy images.
3. `preprocessing_agent`: write text/numeric claims and experiment definitions.
4. `codegen_agent`: use the `explore-data` skill to write and validate a
   bounded data inventory, compare local GPU capacity with the paper's
   full-scale requirements, use the `computation-provider` skill to rent
   matching configured remote compute when needed, plan files, and write code.
5. `audit_agent`: check coverage, install dependencies, smoke-test, and write the replication plan.
6. `replicate_agent`: execute every experiment and write evidence.
7. `report_agents`: sequentially compare each experiment with the paper in one report.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent failure stops the run explicitly.

## Persistent artifacts

```text
runs/<run_id>/
├── manifest.json
├── preflight/resources.json
├── preprocessing/paper.md
├── preprocessing/artifacts/
├── preprocessing/claims.json
├── preprocessing/experiment_todo.json
├── preprocessing/preprocessing_transcript.jsonl
├── codegen/codebase/data_inventory.json
├── codegen/codebase/codegen_plan.json
├── codegen/codegen_transcript.jsonl
├── audit/replicate_plan.json
├── audit/audit_transcript.jsonl
├── replication/<experiment_id>/result.json
├── replication/replication_transcript.jsonl
├── report/reproduction_report.md
├── report/<experiment_id>_transcript.jsonl
├── prompts/
├── system_maintenance/dataset/patch.json
└── remote_compute/
```

Claims have unique `claim_id` values and are limited to `text` or `numeric`.
Experiments have unique `experiment_id` values and list their claim IDs and
paper artifact labels. The replication plan and result files must preserve
those mappings. The data inventory records the configured raw root, adapter,
bounded scan limits, catalog, explored file samples, warnings, and whether a
scan was truncated. With no `--data` input it must explicitly report
`not_supplied` and contain no catalog or samples.

Each run initializes `system_maintenance/dataset/patch.json` as an empty JSON
array. When code generation naturally encounters an omission in a dataset
document, it may add an object containing exactly `"file name"` and
`"patch_content"`; it does not proactively search for omissions or modify the
read-only source dataset. The patch content follows the target document's
structure and remains a reviewable run artifact rather than being applied
automatically.

## Agent boundaries

- Source prompts live under `templates/<stage>/`; runtime skills live under
  `templates/skills/`. Neither is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
- Each agent invocation's provider event stream is preserved as a JSONL
  transcript beside that stage's artifacts. Transcript files are diagnostic
  records and are never used as the agent's structured result.
- Replication agents do not receive paper target values.
- Audit agents may modify the writable codebase but may not change model
  semantics, introduce fallback plans, or hardcode paper results.
- Remote compute access is exposed through the `computation-provider` skill;
  its first supported provider is AutoDL. Only instances created by the current
  run may be automatically powered off or released. After replication finishes
  and required outputs are transferred, the replicate stage must release them;
  host cleanup retries release on failure paths.

## Acceptance

Run `pytest`, `ruff check .`, and `python -m medai.cli --help`. Tests mock
provider, MinerU, AutoDL, and SSH boundaries; tests never rent hardware.
