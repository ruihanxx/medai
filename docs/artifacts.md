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
├── codegen/codegen_agent_result.json  # direct Codex terminal status
├── codegen/cloud_pull/commands/  # opted-in Codex cloud handoff only
│   ├── command_001.json
│   ├── command_001.log
│   └── command_001_result.json
├── codegen/audit/attempt_001/
│   ├── audit_report.json
│   ├── audit_transcript.jsonl
│   ├── scripts/
│   └── results/
├── codegen/cohort_refine/attempt_001/  # only after a failed audit
│   └── cohort_refine_transcript.jsonl
├── plan/replicate_plan.json
├── plan/plan_transcript.jsonl
├── replication/replication_log.json
├── replication/evidence_summary.json
├── replication/<experiment_id>/smart_replicate_log.json  # smart mode only
├── replication/replication_transcript.jsonl
├── report/reproduction_report.md
├── report/<experiment_id>_transcript.jsonl
├── prompts/
│   ├── audit_attempt_001.md
│   ├── audit_attempt_001_resume_001.md  # incomplete direct-Codex audit only
│   ├── <stage>_validation_resume_001.md  # bounded direct-Codex artifact repair
│   ├── cohort_refine_attempt_001.md  # only after a failed audit
│   ├── codegen_agent_result.schema.json  # direct Codex only
│   ├── codegen_cloud_pull_command.schema.json  # opted-in cloud handoff only
│   ├── codegen_cloud_pull_resume_001.md
│   └── replicate_agent_validation_resume_001.md
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
runs/<run_id>/autoresearch/campaign_<NNN>/
├── manifest.json
├── preflight/resources.json
├── eligibility/eligibility.json
├── experiment_setup/experiment_weights.json
├── experiment_setup/experiment_weighting_transcript.jsonl
├── experiment_setup/experiment_contracts.json
├── experiment_setup/experiment_contracts_transcript.jsonl
├── idea_generation/candidates.json
├── rounds/round_001/
│   ├── ideas.json
│   ├── idea_generation_transcript.jsonl
│   ├── ideas/idea_01/
│   │   ├── codegen/codebase/
│   │   ├── codegen/implementation_plan.json
│   │   ├── audit/audit.json
│   │   ├── plan/experiment_plan.json
│   │   ├── plan/cloud_pull/commands/  # opted-in Codex cloud handoff only
│   │   ├── experiment/experiment_log.json
│   │   ├── experiment/evidence_summary.json
│   │   ├── experiment/environment/{setup.sh,environment.json,setup.log,validation.json}
│   │   ├── experiment/artifacts/  # orchestration-confined remote downloads
│   │   ├── experiment/commands/  # remote Codex experiments only
│   │   └── assessment/assessment.json
│   └── round_summary.json
├── report/auto_research_report.md
├── report/idea_metric_comparison.png
├── report/idea_status_overview.png
├── prompts/
└── remote_compute/
    ├── instance.json
    └── cloud-inventory.v1.json  # cloud-backed campaigns only
```

Each Auto Research experiment contract records immutable data, prediction, and
evaluation boundaries; baseline representation, training target, loss, and
training descriptions; and the existing representation, training, and
integration paths eligible for declared refinement changes. A contract's
`metrics` field is one compact agent-written sentence naming the
unchanged evaluator metrics; `primary_metric` separately names the single numeric
metric used for baseline/refinement assessment. Only strict supervised
prediction experiments selected by `experiment_weights.json` receive contracts.
An implementation plan classifies the idea as input-representation, model,
and/or training-strategy work. Its `refine_file_list` records every existing file to modify and how;
`new_file_list` records every file to add and how. Refine paths must come from
the contract-declared representation, training, or integration paths, while new
paths must not exist in the base codebase. Paths are unique across both lists,
at least one list is non-empty, and model refinements require a new file. The
audit records `refinement_only` and six ordered checks per experiment: data,
prediction target, input representation, evaluator-facing output, training,
and evaluation.

Each assessment comparison retains the actual baseline/refinement primary-metric
values and their absolute and relative deltas. Its `score` is an integer from -5
through 5 assigned from the experimental evidence and original study context,
with a non-empty `score_rationale`; it is not a rescaled relative delta.
`weighted_score` is the frozen experiment weight multiplied by that score, and
the assessment total is the unrenormalized sum. An unavailable comparison has
null score fields and makes the total null.

`idea_generation/candidates.json` is the campaign-wide unused-candidate pool.
It records a monotonic `next_candidate_index`, up to six candidates, and a
temporary `selected_candidate_ids` list. Each candidate has a stable `C0001`
ID, problem, methods, motivation, and structured paper/experiment/literature
evidence. Before completing a round, orchestration requires six reviewed
candidates and three selected IDs, removes those selected candidate objects,
clears the selection list, and leaves the remaining candidates for later rounds.

Each `rounds/round_<NNN>/ideas.json` records the round index and exactly three
ordered ideas with the canonical round idea IDs. Every idea contains a non-empty
description, motivation, and one or more provenance objects; each provenance
object contains exactly an identifiable `reference` and a `support` statement.

Claims have unique `claim_id` values, are limited to `text` or `numeric`, and
record a `final` or `validation` role plus a verbatim provenance quote.
Experiments have unique `experiment_id` values and list their claim IDs, paper
artifact labels, and an evidence-bound, one-sentence `computational_demand`.
That sentence records paper-stated full-scale resources and clearly labels any
method- or scale-based inference for omitted resources. The replication plan
uses ordered steps whose
`verifies` lists collectively cover those claim IDs and artifact labels. The
replication log covers the plan steps in order, and every result-producing step
names real output files or directories inside the copied codebase or replication
directory. The evidence summary records the execution environment. Its core
environment fields record Python, GPU availability/model, and key package
versions; additional environment metadata is accepted for auditability. The
reproduction report contains exactly three top-level audit sections:
per-experiment claim/artifact comparisons, a verdict for every validation
anchor, and one replication risk for every `codegen_plan.json` ambiguity.

For Codex replication, the agent executes and monitors its commands inside one
turn. The initial and artifact-repair events share
`replication_transcript.jsonl`; a failed final validation creates
`prompts/replicate_agent_validation_resume_<NNN>.md`. New runs do not create
replication command JSON, log, or result artifacts. Rollback archives retain
these prompts and also preserve legacy command artifacts from earlier runs.

For an opted-in Codex cloud handoff, each
`codegen/cloud_pull/commands/command_<NNN>.json` is the single requested
foreground monitor request. It contains `status`, nullable `command`, and
nullable `error`: `command` runs the reviewed monitor, while `blocked` or
`failed` terminates codegen before local orchestration executes anything. Its
`.log` contains merged local stdout/stderr and
its `_result.json` records the command, exit code, duration, log path, and the
cloud-state validation error when the same Codex session must prepare and hand
off another monitor command. These command artifacts survive an explicit CLI
resume, but the temporary Codex session ID does not.

Every direct-Codex codegen turn writes `codegen_agent_result.json` with required
`status` and nullable `error` fields. `completed` requires `error: null` and is
necessary but not sufficient for stage completion; orchestration then validates
the canonical codegen artifacts. `blocked` and `failed` require a non-empty
error and terminate the stage before artifact-repair resumes.

Auto Research planning cloud handoff stores the same request/log/result triplet
under each idea's `plan/cloud_pull/commands/`; its schema and resume prompts are
under the campaign `prompts/` tree. Remote Codex experiments store one
request/log/result triplet per structured operation under
`experiment/commands/`. A request contains exactly one `remote_exec` command or
one `download` source/destination pair; all four schema properties are required,
with fields unused by the selected operation set to `null`. The result records
the operation, normalized local destination when applicable, exit code,
duration, log path, and artifact-validation error. Remote results persist
beneath the campaign `work/artifacts/<idea_id>/` root, while downloads are
confined to the matching local `experiment/artifacts/` directory. A
mother-environment setup failure uses the same result/log pair and records in
`artifact_validation_error` that the requested operation did not run. Explicit
CLI resume retains these files but does not persist either temporary session
ID.

An Auto Research `experiment/environment/validation.json` is orchestration-owned
and records the SHA-256 hashes of the `setup.sh` and `environment.json` revision
that most recently passed remote setup. A missing or mismatched marker makes the
definition unvalidated; orchestration records new hashes only after setup
succeeds.

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
aggregate statistics, logs, and the report into these local paths. The compact
JSON report contains exactly `verdict` and `issues`. Each issue contains exactly
non-empty `evidence`, `diagnosis`, and `required_fix` strings. `evidence`
records concise observations and supporting result/log paths; `diagnosis`
records the evidence-bound causal defect rather than only its symptom; and
`required_fix` records the testable correction contract. `PASS` requires an
empty issue list and `FAIL` requires the complete accumulated set of distinct
actionable issues, with at least one issue. Legacy Markdown reports retain
read-only verdict compatibility. Audit reports are stage artifacts and do not
change the reproduction report's three-section contract.

For direct Codex, a missing or invalid compact report after a successful agent
turn creates `prompts/audit_attempt_<NNN>_resume_<NNN>.md` and resumes the same
temporary session. Resumed events append to the attempt transcript and reuse
the existing scripts, results, and remote process; they do not create another
scientific audit attempt. A valid report is the only successful completion
artifact.

For other direct-Codex Replicate Agent stages, a failed owned-artifact check
creates `prompts/<stage>_validation_resume_<NNN>.md`. The prompt records the
exact validation error and canonical artifact paths, and resumed events append
to the original stage transcript. At most two repair turns occur in one stage
invocation; failed checks remain visible even when a later repair succeeds.

Each successful cohort-refinement round retains its transcript in a numbered
attempt directory. A provider retry reuses the same directory and transcript
archive convention instead of consuming another scientific round.

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

A cloud-backed Auto Research manifest inherits the same public cloud fields and
keeps local `data` null. Its base fingerprint additionally binds the released
base `remote_compute/instance.json` and `cloud-inventory.v1.json`. The inventory
is copied byte-for-byte into the campaign before materialization and is the
required baseline for the initial instance and any one resume replacement.

`remote_compute/instance.json` has a provider-owned `provider_state` whose
schema is defined by the selected adapter. Its common envelope records the
provider, current-run ownership, and release state. Cloud runs additionally
store `provider_state.cloud_drive` with the public fields `drive`, `dataset`,
`completed`, and `target_path`; adapters may store additional non-secret detail.
Provider-specific retry, failure, and history fields are defined only by the
selected adapter and its metadata-selected reference.
Power-off leaves top-level `released` false; only successful irreversible release
changes it to true. Provider-owned history and resource identifiers remain
non-secret. Credentials, hashes, access tokens, and drive secrets are never
state fields. A provider that supports Auto Research pooling records its bounded
member list and active member inside this same canonical file. The active
provider fields remain the only target for provider actions; release is complete
only after every owned pool member is confirmed destroyed.

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
