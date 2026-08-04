# Agent and Skill Boundary Contract

- Replicate prompts live under `templates/<stage>/`; Auto Research prompts live
  under `templates/autoresearch/<stage>/`; runtime skills live under
  `templates/skills/`. None is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
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
- Remote compute access is exposed through the `computation-provider` skill;
  its first supported provider is AutoDL. Only instances created by the current
  run may be automatically powered off or released. After replication finishes
  and required outputs are transferred, the replicate stage must release them;
  host cleanup retries release on failure paths. The generic
  `remote_compute/instance.json` records the selected provider and common
  lifecycle state; each provider reference defines its provider-specific state.
- Before an AutoDL instance is created, the skill must verify that its GPU
  specification belongs to the current Pro pool. If the paper GPU is absent,
  it may use only the closest documented pool GPU with at least the paper VRAM,
  recording the hardware divergence. Paper-stated software versions require the
  closest compatible official image UUID; without stated versions, the
  configured default image UUID is used. The provider state records the
  selected non-secret GPU and image identifiers.
- When a paper explicitly reports GPU hardware for its full experiment,
  codegen treats its GPU count and per-GPU VRAM as a required capacity floor.
  If local capacity is below that floor, codegen must use configured remote
  compute; CPU feasibility or a smaller inferred workload does not permit a
  CPU substitution.
