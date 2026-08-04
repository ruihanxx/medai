# Agent and Skill Boundary Contract

- Replicate prompts live under `templates/<stage>/`; Auto Research prompts live
  under `templates/autoresearch/<stage>/`; runtime skills live under
  `templates/skills/`. None is stored under `src/`.
- Prompts are rendered with Jinja2 and saved before invocation.
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
- Remote compute access is exposed through the `computation-provider` skill;
  its first supported provider is AutoDL. Only instances created by the current
  run may be automatically powered off or released. After replication finishes
  and required outputs are transferred, the replicate stage must release them;
  host cleanup retries release on failure paths. The generic
  `remote_compute/instance.json` records the selected provider and common
  lifecycle state; each provider reference defines its provider-specific state.
