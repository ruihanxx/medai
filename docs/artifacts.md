# Persistent Artifact Contract

Replication runs use the following canonical paths:

```text
runs/<run_id>/
├── manifest.json  # canonical pipeline state and input fingerprint
├── preflight/resources.json
├── preprocessing/paper.md  # MinerU Markdown audited for asset labels and formulas
├── preprocessing/artifacts/
├── preprocessing/claims.json
├── preprocessing/experiment_todo.json
├── preprocessing/preprocessing_transcript.jsonl
├── codegen/codebase/codegen_plan.json
├── codegen/codegen_transcript.jsonl
├── codegen/audit/attempt_001/
│   ├── audit_report.md
│   ├── audit_transcript.jsonl
│   ├── scripts/
│   └── results/
├── plan/replicate_plan.json
├── plan/plan_transcript.jsonl
├── replication/replication_log.json
├── replication/evidence_summary.json
├── replication/commands/
│   ├── command_001.json
│   ├── command_001.log
│   └── command_001_result.json
├── replication/<experiment_id>/smart_replicate_log.json  # smart mode only
├── replication/replication_transcript.jsonl
├── report/reproduction_report.md
├── report/<experiment_id>_transcript.jsonl
├── prompts/
│   ├── audit_attempt_001.md
│   ├── replicate_command.schema.json
│   └── replicate_resume_001.md
├── resume_history/resume_001/  # only after a replicate/report rollback
│   ├── replication/
│   ├── report/
│   ├── prompts/
│   ├── referenced_codebase_outputs/
│   └── path_mapping.json
├── system_maintenance/dataset/patch.json
├── system_maintenance/skills/corrections.json
└── remote_compute/instance.json
```

Auto Research adds this isolated subtree to a completed base run:

```text
runs/<run_id>/autoresearch/
├── manifest.json
├── preflight/resources.json
├── eligibility/eligibility.json
├── experiment_setup/experiment_weights.json
├── experiment_setup/experiment_weighting_transcript.jsonl
├── experiment_setup/experiment_contracts.json
├── experiment_setup/experiment_contracts_transcript.jsonl
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
Experiments have unique `experiment_id` values and list their claim IDs, paper
artifact labels, and a one-sentence `computational_demand` inferred from the
paper. The replication plan uses ordered steps whose
`verifies` lists collectively cover those claim IDs and artifact labels. The
replication log covers the plan steps in order, and every result-producing step
names real output files or directories inside the copied codebase or replication
directory. The evidence summary records the execution environment. Its core
environment fields record Python, GPU availability/model, and key package
versions; additional environment metadata is accepted for auditability. The
reproduction report contains exactly three top-level audit sections:
per-experiment claim/artifact comparisons, a verdict for every validation
anchor, and one replication risk for every `codegen_plan.json` ambiguity.

For Codex replication, each `replication/commands/command_<NNN>.json` is the
single requested Bash command; its `.log` contains merged local stdout/stderr,
and its `_result.json` records the command, exit code, duration, log path, and
the artifact-validation error when another session turn is required. The
initial and resumed Codex events share `replication_transcript.jsonl`; rendered
resume prompts and the output schema are kept under `prompts/`. Replication
rollback archives retain these prompts as well as the command artifacts.

Each run initializes `system_maintenance/dataset/patch.json` as an empty JSON
array. When code generation naturally encounters an omission in a dataset
document, it may add an object containing exactly `"file name"` and
`"patch_content"`; it does not proactively search for omissions or modify the
read-only source dataset. The patch content follows the target document's
structure and remains a reviewable run artifact rather than being applied
automatically.

Each run also initializes `system_maintenance/skills/corrections.json` as an
empty JSON array. Codegen appends an entry only when a successful remote-compute
procedure conflicts with the selected skill reference. Every entry records the
skill, provider, reference path, discrepancy, resolved procedure, and consulted
official documentation URLs. It is a review artifact, not a permission to edit
the repository skill during the run.

Every scientific preprocessing audit has its own numbered local attempt
directory; technical provider retries remain within that attempt and archive
earlier transcripts using the normal transcript convention. Local-data
audit-only CPU, streaming, or small-batch adapters remain under `scripts/` and
never enter `codegen/codebase/`; preprocessing outputs, command logs, and
statistics remain under `results/`. Cloud-data audits use a separate remote
attempt beneath the codegen remote working directory and copy back only
aggregate statistics, logs, and the report into these local paths. The Markdown
report has no schema or static body validation.
Its sole machine protocol is exactly one verdict marker as the final non-empty
line: `Verdict: PASS` or `Verdict: FAIL`. Audit reports are stage artifacts and
do not change the reproduction report's three-section contract.

Remote-compute objects in codegen, replication, and Auto Research plans require
only `state_path`, `remote_working_dir`, and `remote_dataset_dir`. The directory
fields identify the run-owned remote workspace and the remote read-only dataset
location. Additional provider, resource, image, connection, setup, and rationale
fields are accepted. Schema validation is limited to these three required
fields. Codegen orchestration additionally verifies that `state_path` is the
current run's canonical remote-state path; provider-specific lifecycle
validation remains a runtime provider-script responsibility.

Replication manifest inputs distinguish local and cloud data. A cloud run sets
`clouddrive: true`, `computation_provider`, `computation_provider_config`,
`drive_provider`, `cloud_dataset`, and `cloud_source`, while both `data` and
`data_source` remain null. These fields are part of the resume fingerprint.
`computation_provider_config` contains only metadata-declared non-secret values.
Local runs set the cloud fields to false/null and retain the existing `data` and
`data_source` behavior. Secrets are never persistent artifacts.

`remote_compute/instance.json` has a provider-owned `provider_state` whose
schema is defined by the selected adapter. Its common envelope records the
provider, current-run ownership, and release state. Cloud runs additionally
store `provider_state.cloud_drive` with the public fields `drive`, `dataset`,
`completed`, and `target_path`; adapters may store additional non-secret detail.
Power-off leaves top-level `released` false; only successful irreversible release
changes it to true. Provider-owned history and resource identifiers remain
non-secret. Credentials, hashes, access tokens, and drive secrets are never
state fields.

Each replication rollback archive is immutable by convention: an existing
`resume_<NNN>` target makes resume fail rather than overwrite history.
`path_mapping.json` records the original logged codebase output, its resolved
source, its archived copy, unresolved log references, and any partial-log parse
error. The canonical `replication/` and `report/` directories are recreated
empty for the new attempt; codebase and plan artifacts remain canonical.

When final release fails, `manifest.json.cleanup_warning` records
`recorded_at`, `operation`, and the non-secret error while overall status stays
`completed`. The canonical instance state remains the input for a deliberate
manual release; a later validation-only invocation does not retry it.
