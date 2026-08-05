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
   full-scale requirements, use the `computation-provider` skill to rent
   matching configured remote compute when needed, plan files, and write code.
   Cloud-drive mode always selects AutoDL: codegen materializes the complete
   dataset before any data inspection, then records the completed state's
   read-only target as `remote_dataset_dir`.
5. `audit_agent`: run real-data preprocessing, compute paper-aware cohort and
   data-quality sanity statistics, and write a free-form audit report. Local
   data runs keep the existing isolated local audit and never connect to remote
   compute. Cloud-drive runs instead reuse codegen's active instance, remote
   dataset, and preprocessing implementation in an independent remote audit
   directory. They execute complete preprocessing with small audit-only
   instrumentation, prohibit training/tuning/evaluation and local CPU adapters,
   and retrieve only aggregate statistics, logs, and the report—not raw or
   row-level data.
6. `plan_agent`: check coverage, install dependencies, smoke-test, and write the
   replication plan.
7. `replicate_agent`: execute every experiment and write evidence.
8. `report_agents`: sequentially update one report with per-experiment
   claim/artifact comparisons, validation-anchor assessments, and a risk list
   derived from code-generation ambiguities.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent failure stops the run explicitly.

A failed remote interaction starts bounded, safe recovery: the agent begins
with the selected provider reference, may consult official provider
documentation and use reasoned diagnostics, and must not blindly repeat a
billable operation. When the provider reference states that no read-only
inventory query is available, the agent rents the selected resource directly.
An explicit no-inventory response permits exactly one attempt with a stronger
eligible GPU that preserves every original requirement; a failed retry is
terminal. If recovery remains unsuccessful, the invoking Codex agent exits
nonzero. When codegen records a remote-compute plan, orchestration statically
validates its current-run state path, remote working directory, and remote
dataset directory before the stage completes. For cloud runs it also requires
an active `completed` cloud-drive state and exact agreement between that state's
target and every codegen/replication plan `remote_dataset_dir`. Additional
provider metadata is accepted, and other provider-specific lifecycle validation
occurs at runtime. A
successful procedure that conflicts with the skill reference is recorded in
`system_maintenance/skills/corrections.json`, not applied to the repository
skill during the run.

Audit PASS proceeds to planning. Audit FAIL returns to codegen with the failed
report and permits changes only to the complete preprocessing chain and related
configuration; model, training, evaluation, and generated results remain out of
scope. The codegen ambiguity record must capture the evidence-based resolution.
There may be at most three such rewrites after the initial audit, for four audit
attempts total. The fourth FAIL stops the run after preserving every report.
Judgment is paper- and data-type-aware: no universal retention or balance
threshold is imposed, and paper-expected natural imbalance is not itself a
failure.

`manifest.json` is the canonical pipeline state. It records a versioned input
fingerprint, overall and per-stage status, attempts, timestamps, outputs, and
stage checkpoints. On reuse of an output directory, version 1 manifests are
migrated, the paper hash and output-affecting configuration must match, and
only stages marked `completed` are skipped. Every skipped stage reloads and
validates its canonical artifacts before downstream work proceeds. A `running`
or `failed` stage starts another attempt while retaining its writable artifacts.
Failure handling reloads the current manifest before recording the error so
stage updates are not overwritten by stale state. Code generation records
source preparation before invoking its agent; replication continues from the
valid ordered prefix in its step log; report generation checkpoints every
completed experiment. A completed run is therefore safe to invoke again and
becomes a validation-only no-op.

The audit checkpoint records `audited_codegen_attempt`, `verdict`, `report_path`,
and `rewrite_rounds_used`. A completed verdict for the current codegen attempt is
reused; a newer codegen attempt is audited again. Audit or provider technical
failure resumes the same scientific audit directory and does not consume a
rewrite. A persisted fourth FAIL remains terminal on resume. When audit-driven
codegen supersedes a legacy completed implementation, downstream plan,
replication, and report stages are invalidated and rerun.

Failure cleanup releases the current cloud instance. On an explicit resume,
codegen creates at most one replacement only after the state proves the old
instance was released, then rematerializes the dataset. The provider script
archives non-secret selection, cloud state, and release time in instance
history. An unreleased instance or failed cleanup blocks another rental. A
completed run may validate its released final state without renting again.
