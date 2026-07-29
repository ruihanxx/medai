# Project Contract

## CLI and isolation

`./medai` requires `--paper`, `--provider`, and `--output`; `--repo` and
`--data` are optional. Supported providers are `claude`, `codex`, and
`codex-siliconflow`. Paper, repository, data, provider configuration, and CLI
credentials are mounted read-only. The output directory is writable and may
not be placed inside the repository or data input.

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
4. `codegen_agent`: explore data, plan resources/files, and write code.
5. `audit_agent`: check coverage, install dependencies, smoke-test, and write the replication plan.
6. `replicate_agent`: execute every experiment and write evidence.
7. `report_agents`: sequentially compare each experiment with the paper in one report.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent failure stops the run explicitly.

## Persistent artifacts

```text
<output>/
├── manifest.json
├── preflight/resources.json
├── preprocessing/paper.md
├── preprocessing/artifacts/
├── preprocessing/claims.json
├── preprocessing/experiment_todo.json
├── codegen/codebase/codegen_plan.json
├── audit/replicate_plan.json
├── replication/<experiment_id>/result.json
├── report/reproduction_report.md
├── prompts/
└── logs/
```

Claims have unique `claim_id` values and are limited to `text` or `numeric`.
Experiments have unique `experiment_id` values and list their claim IDs and
paper artifact labels. The replication plan and result files must preserve
those mappings.

## Agent boundaries

- Source prompts live under `templates/<stage>/`; runtime skills live under
  `templates/skills/`. Neither is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
- Agent subprocess output is preserved as JSONL.
- Replication agents do not receive paper target values.
- Audit agents may modify the writable codebase but may not change model
  semantics, introduce fallback plans, or hardcode paper results.
- AutoDL access is exposed through a skill. Only instances created by the
  current run may be automatically powered off and released.

## Acceptance

Run `pytest`, `ruff check .`, and `python -m medai.cli --help`. Tests mock
provider, MinerU, AutoDL, and SSH boundaries; tests never rent hardware.
