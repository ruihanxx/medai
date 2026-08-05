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
├── replication/<experiment_id>/smart_replicate_log.json  # smart mode only
├── replication/replication_transcript.jsonl
├── report/reproduction_report.md
├── report/<experiment_id>_transcript.jsonl
├── prompts/
│   └── audit_attempt_001.md
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

Every scientific preprocessing audit has its own numbered attempt directory;
technical provider retries remain within that directory and archive earlier
transcripts using the normal transcript convention. Audit-only CPU, streaming,
or small-batch adapters remain under `scripts/` and never enter
`codegen/codebase/`; preprocessing outputs, command logs, and statistics remain
under `results/`. The Markdown report has no schema or static body validation.
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
`clouddrive: true`, `drive_provider`, `cloud_dataset`, and `cloud_source`, while
both `data` and `data_source` remain null. These fields are part of the resume
fingerprint. Local runs set the cloud fields to false/null and retain the
existing `data` and `data_source` behavior. Secrets used to access AutoPanel or
the drive are never persistent artifacts.

For AutoDL, `remote_compute/instance.json` stores current non-secret resource
selection and lifecycle fields under `provider_state`. Cloud runs additionally
store `provider_state.cloud_drive` with provider, dataset, fixed source,
staging, and target paths, ownership marker, status and timestamps, task ID,
and remote/local file-count and byte-total aggregates. A released instance
retained across an explicit resume moves these non-secret fields and its release
time into `provider_state.instance_history` before one replacement becomes
current. Passwords, password hashes, Jupyter or AutoPanel tokens, and drive
credentials are never state fields.
