# Replication Workflow Contract

The LangGraph stages are:

1. `preflight`: validate inputs and record CPU, RAM, disk, and GPU resources.
2. `preprocess_pdf`: import the host MinerU result, convert it to canonical
   Markdown, and copy images. Host MinerU output remains temporary; only the
   canonical Markdown and artifacts persist in the run directory.
3. `preprocessing_agent`: audit `paper.md` in place by labeling linked
   Figure/Table assets with captions and correcting image-verified LaTeX,
   then write text/numeric claims and experiment definitions.
4. `codegen_agent`: inspect supplied data through bounded, read-only,
   non-executing reads, identify every paper-underspecified implementation
   decision before coding, resolve each using applicable medical knowledge and
   standard medical-research methods, record the executable resolution as a
   code-generation ambiguity, compare local GPU capacity with the paper's
   full-scale requirements, use the `computation-provider` skill when remote
   compute is required, plan files, and write code. Paper-stated GPU count and
   per-GPU VRAM are hard capacity floors; a smaller inferred workload or CPU
   feasibility cannot substitute when local capacity is below them. A
   paper-required file absent from the supplied dataset terminates codegen
   without invention or substitution, and preprocessing audit does not start.
   Cloud-drive mode always selects the configured provider: codegen materializes
   the complete dataset before any data inspection, then records the completed state's
   read-only target as `remote_dataset_dir`.
5. `audit_agent`: exhaustively run real-data preprocessing and every applicable
   independent paper-aware cohort and data-quality check, then write one compact
   JSON report containing the complete discovered issue set. A generated-code
   exception is accumulated as an issue and root-caused; it does not stop
   independently executable checks. Local data runs keep the existing isolated
   local audit and never connect to remote compute. Cloud-drive runs instead
   reuse codegen's active instance, remote dataset, and preprocessing
   implementation in an independent remote audit directory. They execute
   complete preprocessing with small audit-only instrumentation, prohibit
   training/tuning/evaluation and local CPU adapters, and retrieve only
   aggregate statistics, logs, and the report—not raw or row-level data.
6. `cohort_refine_agent`: after a failed audit, fix every reported cohort
   construction, data-loading, or preprocessing issue; it may update only the
   code-generation plan's `ambiguities` list and may not change models,
   training, evaluation, or generated results.
7. `plan_agent`: check coverage, install dependencies, smoke-test, and write the
   replication plan.
8. `replicate_agent`: execute every experiment and write evidence.
9. `report_agents`: sequentially update one report with per-experiment
   claim/artifact comparisons, validation-anchor assessments, and a risk list
   derived from code-generation ambiguities.

For a cloud drive whose metadata opts into handoff, direct Codex codegen first
prepares and powers off the initialized SSH-ready instance, then returns one
foreground local cloud-monitor command. Orchestration runs that command while
the Codex process is absent and resumes the same session after its terminal
result. A successful resume proceeds only from completed cloud state; an
incomplete result returns to that session for bounded diagnostics and a fresh
prepare/monitor handoff.

For `provider=codex` only, replication uses an intra-invocation command handoff
loop. Codex returns one schema-validated non-empty Bash command, orchestration
runs it locally from the codebase while streaming and saving its combined log,
then validates the canonical replication artifacts. A failed command or an
incomplete validation resumes the same explicit Codex session with that saved
result so Codex can debug or choose the next command. Completion is solely a
successful artifact validation; command exit status is diagnostic, not an
automatic stage failure. This session is intentionally temporary: an explicit
CLI resume still archives and restarts the replication attempt as described
below.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent or technical failure stops the run explicitly. The sole scientific-verdict
exception is an audit FAIL after all cohort-refinement rounds, which continues
to planning while retaining the failed report and checkpoint.

A failed remote interaction follows the bounded recovery procedure in the
metadata-selected provider reference. The agent may consult official provider
documentation and use reasoned diagnostics but must not guess or blindly repeat
a billable action. Provider-specific inventory, fallback, failed-create, and
replacement rules live only in that reference. If recovery remains
unsuccessful, the invoking agent exits nonzero. Orchestration validates remote
plans and cloud state against `artifacts.md`; a successful procedure that
conflicts with the selected reference is recorded in the canonical skill
correction artifact rather than applied to the repository skill during the run.

Audit PASS proceeds to planning. Audit FAIL enters cohort refinement with the
failed report and permits changes only to cohort construction, data loading,
preprocessing, directly related data configuration, and the code-generation
plan's `ambiguities` list; all other plan fields, models, training, evaluation,
and generated results remain read-only. A new ambiguity is recorded only after
the paper is rechecked and confirmed to be underspecified, then resolved using
applicable medical expertise and standard medical-research methods.
There may be at most three refinement rounds after the initial audit, for four
audit attempts total. The fourth FAIL proceeds to planning after preserving
every report and recording that refinement was exhausted.
Judgment is paper- and data-type-aware: no universal retention or balance
threshold is imposed, and paper-expected natural imbalance is not itself a
failure. Before deciding the verdict, audit instrumentation records each
paper-required mapped concept or derived feature across source, mapping,
normalization/acceptance, and final-output boundaries. The agent accumulates
all distinct actionable root causes supported by the completed checks and does
not use the first failure as an early-exit condition. An audit-infrastructure
interruption that prevents the complete pass exits nonzero for a same-attempt
technical retry instead of producing an incomplete scientific verdict.

`manifest.json` is the canonical pipeline state. It records a versioned input
fingerprint, overall and per-stage status, attempts, timestamps, outputs, and
stage checkpoints. On reuse of an output directory, version 1 manifests are
migrated, the paper hash and output-affecting configuration must match, and
only stages marked `completed` are skipped. Every skipped stage reloads and
validates its canonical artifacts before downstream work proceeds. A `running`
or `failed` stage before replication starts another attempt while retaining its
writable artifacts.
Failure handling reloads the current manifest before recording the error so
stage updates are not overwritten by stale state. Code generation records
source preparation before invoking its agent; report generation checkpoints
every completed experiment. A completed run is therefore safe to invoke again
and becomes a validation-only no-op.

An explicit Replicate resume performs one remote reconciliation after manifest
resume and before LangGraph. A released instance is replaced from its recorded
actual GPU specification/count and image. A shutdown instance is powered on; a
running instance gets one harmless SSH probe. An SSH failure permits replacement
only after the old instance is successfully powered off and released. A
provider-confirmed missing instance may be replaced directly, while ambiguous
API/network errors fail without a second rental. Replacement may try only the
bounded alternatives documented by the selected provider reference, and each
`resume_count` permits at most one replacement. Missing, corrupt, or incomplete
remote state fails explicitly.

If replication ever started and report is incomplete, the old replication and
report attempt is not checkpointed. It is archived under
`resume_history/resume_<NNN>/` together with its rendered prompts and copies of
codebase outputs cited by its replication log; `path_mapping.json` records those
copies. Canonical replication/report paths are recreated empty, both stages are
invalidated, and replication restarts at plan step 1. If replacement occurs
before replication starts, codegen and downstream stages are invalidated with
an `infrastructure_resume` checkpoint while the prepared local codebase remains.
A reused instance keeps the existing earlier-stage checkpoint. Cloud-drive runs
invoke the idempotent `cloud-pull` before every replication attempt.

The audit checkpoint records `audited_codegen_attempt`, `audited_refine_round`,
`verdict`, `report_path`, `refine_rounds_used`, and
`refinement_exhausted`. A completed verdict is reused only for the same codegen
attempt and completed refinement round. Audit or provider technical failure
resumes the same scientific audit directory and does not consume a refinement.
Each successful cohort refinement records its completed round and source audit
report; a technical retry reuses that round. Cohort refinement invalidates stale
planning, replication, and report stages before changing preprocessing.

Replication follows the host-owned lifecycle in `execution.md`: plans finish by
downloading and validating outputs and then powering off, while release occurs
only after report validation and pipeline completion. The only earlier release
is bounded resume reconciliation before one replacement. Legacy stored plans
are not rewritten; before resuming one, its old release step must be changed
manually to power-off.
