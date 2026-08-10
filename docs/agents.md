# Agent and Skill Boundary Contract

- Every workflow-stage prompt, shared orchestration contract, and generic
  example must remain provider- and dataset-agnostic. They may refer only to
  the selected provider reference and supplied dataset metadata. Concrete
  provider names, API identifiers, commands, paths, configuration variables,
  dataset names, schemas, cohort rules, and file layouts must live only in the
  corresponding skill reference or script, or in dataset-specific
  documentation or adapters. Prompt examples must use placeholders. A new
  provider or dataset must never require hard-coding its identity or details
  into a workflow prompt.
- Replicate prompts live under `templates/<stage>/`; Auto Research prompts live
  under `templates/autoresearch/<stage>/`; runtime skills live under
  `templates/skills/`. None is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
- The preprocessing agent records an evidence-bound, one-sentence
  `computational_demand` for every extracted experiment. It searches the paper
  for `nvidia`, `memory`, `gpu`, `cpu`, `GB`, and `rtx`, records paper-stated
  resources, and labels method- and scale-based resource inferences.
- The preprocessing-audit and cohort-refinement prompts form the independent
  module between codegen and planning. They live at
  `templates/cohort_refine/audit_session_instructions.md` and
  `templates/cohort_refine/session_instructions.md`; rendered prompts are saved
  as `prompts/audit_attempt_<NNN>.md` and
  `prompts/cohort_refine_attempt_<NNN>.md`.
- Each agent invocation's provider event stream is preserved as a JSONL
  transcript beside that stage's artifacts. Before a retried invocation, an
  existing transcript is preserved as `<name>.attempt-<N>.jsonl`. Transcript
  files are diagnostic records and are never used as the agent's structured
  result.
- Codex replication and opted-in cloud codegen are the exceptions to the
  one-turn agent pattern. Their initial turns and explicit-session resume turns
  append to one transcript and use the sole structured response
  `{"command":"<non-empty bash command>"}`. Replication validates its canonical
  artifacts after each local command. Cloud codegen first uses the active agent
  to prepare and power off an initialized remote instance, then local
  orchestration runs the returned monitor command and resumes the same session
  after its terminal result. Its cloud data remains unavailable until provider
  state is completed. The prompt permits file inspection, code edits, and
  lightweight interaction in Codex; long-running experiments, test suites, and
  remote monitoring are handed back as the foreground command. No `--last`,
  status field, or completion sentinel is used.
- Replication agents do not receive paper target values by default. Smart
  Replicate exposes only claim-level audited anchors and requires the baseline,
  comparisons, hypotheses, changes, commands, and actual round results in
  `smart_replicate_log.json`; it does not expose the paper itself.
- Auto Research experiment weights are generated before code inspection and do
  not receive result artifacts. Experiment contracts trust the completed
  replicate code as the executable source of truth. Auto Research codegen may
  add model files and touch declared integration files only; the experiment
  stage executes the audited new model without modifying source code or
  rerunning the baseline.
- Plan agents may modify the writable codebase but may not change model
  semantics, introduce fallback plans, or hardcode paper results.
- The preprocessing audit agent runs with its local attempt directory as working
  directory and treats `codegen/codebase/` as read-only. For local data it also
  treats source data as read-only, writes only local audit artifacts, never uses
  remote compute, and may make device-only adapters without changing scientific
  semantics. For cloud data it must use the existing computation-provider state,
  copy codegen's remote preprocessing into an independent remote audit attempt,
  add only audit instrumentation, and execute complete preprocessing there. It
  may download only aggregate statistics, logs, and the report; raw or row-level
  data, local CPU adapters, training, tuning, and evaluation are prohibited.
- The preprocessing audit agent accumulates issues throughout the complete
  applicable checklist and writes its report only after every feasible check.
  A generated-code crash is root-caused and recorded but does not end independent
  mapping, unit, boundary, or feature-propagation checks. Each paper-required
  mapped concept or derived feature is traced from aggregate source coverage
  through mapping and normalization/acceptance to its final output. The report
  separates observed `evidence`, causal `diagnosis`, and testable
  `required_fix`; it contains every distinct actionable root cause supported by
  the attempt. A provider or audit-infrastructure interruption that prevents
  this complete pass exits nonzero for a same-attempt technical retry.
- For large raw tables/dataframes, codegen and the preprocessing audit read in
  chunks or bounded batches, immediately perform chunk-eligible preprocessing,
  retain only required columns, and postpone global operations such as
  downsampling until the compact chunk outputs are merged.
- Codegen exits nonzero as soon as it determines that the paper requires a file
  absent from the supplied dataset, regardless of whether the likely cause is
  dataset version, incomplete download, paper error, or another source
  mismatch. It must not invent an absent or derived artifact, generate code that
  waits for it, substitute other data, or proceed to preprocessing audit.
- Cohort refinement reads the paper, codebase, code-generation plan, and latest
  failed audit report. For every issue it uses the reported evidence as the
  observed failure, the diagnosis as the root-cause claim, and the required fix
  as the minimum correction contract. It must fix and verify every reported
  issue before succeeding. It may change only cohort construction, data loading,
  preprocessing, directly related data configuration, and the plan's
  `ambiguities` list; all other plan fields, models, training, tuning,
  evaluation, and result artifacts remain read-only. A newly encountered
  ambiguity is recorded only after rereading the relevant paper text and
  confirming it is genuinely underspecified, then resolving it with applicable
  medical expertise and standard medical-research methods. Local-data
  refinement never operates remote compute. Cloud-data refinement reuses the
  existing instance and may retrieve only aggregate verification output and
  logs; it never rents, releases, reauthorizes, or rematerializes data.
- Remote compute access is exposed through the `computation-provider` skill.
  Provider references resolve provider-specific SSH connection metadata; the
  skill's shared SSH helper owns provider-independent key-first authentication,
  password fallback, command execution, and file transfer.
  Only instances created by the current run may be automatically powered off or
  released. After replication finishes and required outputs are transferred and
  validated, its final plan step powers off the instance without releasing it;
  host orchestration repeats the idempotent power-off after the stage and on
  pre-report failures. Only after report validation and pipeline completion may
  the CLI release it. An unreachable old instance may be released earlier only
  during bounded resume reconciliation and only before creating its single
  replacement. The generic
  `remote_compute/instance.json` records the selected provider and common
  lifecycle state; each provider reference defines its provider-specific
  selection procedure, operations, and state.
- Before an instance is created, the selected provider reference must validate
  the requested resource and image against that provider's supported pool. If
  the paper's exact GPU is absent, selection may use only the closest documented
  eligible GPU with at least the required VRAM and must record the divergence.
  Provider state records the selected non-secret resource and image identifiers.
- If the selected provider reference states that no read-only inventory query
  is available, codegen rents the selected resource directly. Only when that
  request explicitly fails because the selected GPU has no inventory may the
  provider procedure try exactly once with a stronger eligible GPU that still
  satisfies every original requirement. A failed retry is terminal.
- When a paper explicitly reports GPU hardware for its full experiment,
  codegen treats its GPU count and per-GPU VRAM as a required capacity floor.
  If local capacity is below that floor, codegen must use configured remote
  compute; CPU feasibility or a smaller inferred workload does not permit a
  CPU substitution.
- When codegen requires remote compute, it records the exact current-run state
  path, remote working directory, and remote dataset directory in
  `codegen_plan.json`. Orchestration statically validates only these required
  fields and accepts additional provider-specific plan metadata. Cloud-backed
  runs additionally require completed provider cloud state and exact agreement
  between its target and every plan's `remote_dataset_dir`. For every
  remote-compute interaction, including instance creation, the agent starts with
  the selected provider reference but may consult official online documentation
  and use reasoned, non-secret diagnostics for bounded, safe recovery attempts.
  If recovery still fails, it exits nonzero. A successful procedure that
  conflicts with the reference is recorded for review in
  `system_maintenance/skills/corrections.json`; it does not edit repository
  skills during the run.
- Explicit Replicate resume reconciliation is orchestration-owned, not an agent
  action. Codegen receives `infrastructure_resume` only when a replacement before
  replication requires re-upload and environment reconstruction. A resumed
  replication/report attempt is archived and restarted from replication step 1;
  agents must not reuse its old step log as a checkpoint. Auto Research agents
  retain their existing behavior.
