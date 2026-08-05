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
- The base preprocessing-audit prompt lives beside codegen at
  `templates/codegen/audit_session_instructions.md`; rendered prompts are saved
  per scientific attempt as `prompts/audit_attempt_<NNN>.md`.
- Each agent invocation's provider event stream is preserved as a JSONL
  transcript beside that stage's artifacts. Before a retried invocation, an
  existing transcript is preserved as `<name>.attempt-<N>.jsonl`. Transcript
  files are diagnostic records and are never used as the agent's structured
  result.
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
- The preprocessing audit agent runs with its attempt directory as working
  directory. It treats source data and `codegen/codebase/` as read-only, writes
  only audit scripts/results/report artifacts, and may install dependencies only
  locally. It runs full locally feasible preprocessing and paper-aware basic
  statistics without model training, tuning, evaluation, remote-instance access,
  or the `computation-provider` skill. Device-only adaptations may change CPU/GPU
  placement, batching, chunking, or streaming, but not scientific semantics.
- A codegen retry caused by audit reads the latest failed report and may change
  data reading, cohort construction, window/feature aggregation, missing-data
  handling, and related configuration only. It must repair the evidenced root
  cause and update the corresponding ambiguity; it may not alter models,
  training, evaluation, or result artifacts to chase paper values.
- Remote compute access is exposed through the `computation-provider` skill.
  Only instances created by the current run may be automatically powered off or
  released. After replication finishes and required outputs are transferred,
  the replicate stage must release them; host cleanup retries release on
  failure paths. The generic `remote_compute/instance.json` records the
  selected provider and common lifecycle state; each provider reference defines
  its provider-specific selection procedure, operations, and state.
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
- When codegen requires remote compute, it records that decision and the exact
  current-run state path in `codegen_plan.json`. Before codegen completes,
  orchestration validates that the recorded instance is current-run-owned,
  unreleased, and has the required connection state. For every remote-server
  interaction, including instance creation, the agent starts with the selected
  provider reference but may consult official online documentation and use
  reasoned, non-secret diagnostics for bounded, safe recovery attempts. If
  recovery still fails, it exits nonzero. A successful procedure that conflicts
  with the reference is recorded for review in
  `system_maintenance/skills/corrections.json`; it does not edit repository
  skills during the run.
