# Replication Workflow Contract

The LangGraph stages are:

1. `preflight`: validate inputs and record CPU, RAM, disk, and GPU resources.
2. `preprocess_pdf`: import the host MinerU result, convert it to canonical
   Markdown, and copy images. Host MinerU output remains temporary; only the
   canonical Markdown and artifacts persist in the run directory.
3. `preprocessing_agent`: audit `paper.md` in place by labeling linked
   Figure/Table assets with captions and correcting image-verified LaTeX,
   then write text/numeric claims and experiment definitions. Every experiment
   records all logical datasets it consumes, with exact paper names,
   experiment-specific roles, and concrete usage.
4. `codegen_agent`: inspect supplied data through bounded, read-only,
   non-executing reads, identify every paper-underspecified implementation
   decision before coding, resolve each using applicable medical knowledge and
   standard medical-research methods, record the executable resolution as a
   code-generation ambiguity, inventory the selected local dataset, make the
   local-first capacity decision, use the `computation-provider` skill only when
   remote compute is justified, plan files, and write code. Paper-stated GPU
   count and per-GPU VRAM are hard capacity floors; a smaller inferred workload
   or CPU feasibility cannot substitute when local capacity is below them.
   Unstated CPU-only hardware defaults to eight sufficient physical cores;
   larger inferred core counts require explicit parallel-method evidence or a
   representative benchmark beyond the local time limit. Memory follows the
   planned streaming/chunked/out-of-core peak with 20% headroom, disk follows
   actual dataset/work landing points, and uncertainty requires a bounded local
   probe rather than automatic remote selection. A
   paper-required file absent from the supplied dataset terminates codegen
   without invention or substitution, and preprocessing audit does not start.
   Cloud-only mode always selects the configured provider and materializes the
   complete dataset before inspection. A dual-source run makes the same
   local-first capacity decision as a local run, using local data when sufficient
   and the cloud source only with a remote plan. Remote plans record the
   completed state's read-only target as `remote_dataset_dir`.
   Multiple logical datasets may share that root; Codegen inventories and
   implements each experiment-dataset contract separately and stops when the
   extracted contract conflicts with the paper.
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
   The audit covers every declared experiment-dataset pair and retains
   per-dataset evidence before any linkage or pooling.
6. `cohort_refine_agent`: after a failed audit, fix every reported cohort
   construction, data-loading, or preprocessing issue; it may update only the
   code-generation plan's `ambiguities` list and may not change models,
   training, evaluation, or generated results.
7. `plan_agent`: check coverage, install dependencies, smoke-test, and write the
   replication plan. Every data-touching step names the exact datasets and
   explains their separate preparation, role, and combination or comparison.
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

For `provider=codex` only, replication runs as one direct agent session. Codex
executes, monitors, and repairs its own commands before ending the turn; host
orchestration does not inspect or persist individual command results. After a
successful agent return, orchestration validates the complete canonical
replication artifacts. An incomplete validation resumes the same explicit
Codex session for at most two artifact-repair turns. Completion is solely a
successful final artifact validation. This session is intentionally temporary:
an explicit CLI resume still archives and restarts the replication attempt as
described below.

For a direct-Codex preprocessing audit, a successfully returned agent turn is
not stage completion by itself. Orchestration validates the attempt's compact
`audit_report.json`; a missing or invalid report resumes the same temporary
Codex session with the validation error and existing audit context. The resumed
agent must inspect and continue any process it already launched instead of
starting duplicate work. Initial and resumed turns append to one transcript,
and these artifact-driven resumes remain inside the same scientific audit
attempt and refinement count. Other providers retain one-turn audit behavior
and fail immediately when their returned report is missing or invalid.

The other direct-Codex Agent stages use the same artifact-driven completion
rule. Preprocessing, final codegen validation, cohort refinement, planning, and
each per-experiment report validation resume the same temporary session with
the exact validation error and owned artifact paths. Each stage permits at most
two repair turns, preserves valid work, and prohibits repeating completed
experiments, data transfers, provider provisioning, or lifecycle actions merely
to repair an artifact contract. Other providers retain one-turn behavior and
fail immediately on invalid artifacts. Completed-stage validation during an
explicit CLI resume does not reuse a process-local session.

Before direct-Codex codegen artifact validation, orchestration reads the strict
stage result. `blocked` and `failed` terminate immediately with the recorded
error and do not consume artifact-repair turns. `completed` permits validation
but cannot complete the stage without valid canonical artifacts. The same
result contract applies to codegen repair turns. Cloud-pull preparation uses an
equivalent command-or-terminal result so a terminal condition never requires a
fabricated monitor command or shell-level attempt to alter the Codex CLI exit.

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
stage checkpoints. On reuse of an output directory, manifest versions 1–3 are
migrated to the plural dataset fields, the paper hash and output-affecting configuration must match, and
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
