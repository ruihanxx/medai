# Agent, Prompt, and Skill Boundary Contract

This file owns agent-facing information, mutation, invocation, and skill
boundaries. Workflow ordering, retries, and resume behavior belong in
`replication.md` or `autoresearch.md`; persistent paths and schemas belong in
`artifacts.md`; host-owned remote lifecycle belongs in `execution.md`;
provider-specific procedures belong in the metadata-selected runtime skill
reference.

## Prompt and transcript contract

- Generic stage prompts and shared examples remain provider- and
  dataset-agnostic. Provider or dataset names, APIs, commands, credentials,
  configuration, schemas, cohort rules, and layouts live only in the selected
  skill reference or script, dataset documentation, or adapter. Examples use
  placeholders, and adding a provider or dataset never requires hard-coding it
  into a generic workflow prompt.
- Replicate prompts live under `templates/<stage>/`, Auto Research prompts under
  `templates/autoresearch/<stage>/`, and runtime skills under
  `templates/skills/`; none is stored under `src/`. Preprocessing audit and
  cohort refinement use `templates/cohort_refine/audit_session_instructions.md`
  and `templates/cohort_refine/session_instructions.md`; an incomplete
  direct-Codex audit resumes with
  `templates/cohort_refine/audit_resume_instructions.md`.
- Prompts are rendered with Jinja2 and persisted before invocation. Their
  canonical output paths are defined in `artifacts.md`.
- Every invocation preserves its provider event stream as a JSONL transcript
  beside the stage artifacts. Before a retry overwrites a transcript, the old
  file is archived as `<name>.attempt-<N>.jsonl`. A transcript is diagnostic
  evidence, never the structured agent result.

## Invocation modes

One-turn invocation is the default. These direct-Codex modes instead keep one
temporary session across explicit orchestration handoffs:

| Mode | Structured request | Orchestration boundary |
| --- | --- | --- |
| Replication | `{"command":"<non-empty bash command>"}` | Run the foreground command locally, persist its result, validate canonical artifacts, and resume only when validation requires another turn. |
| Opted-in cloud codegen or Auto Research planning | `{"command":"<non-empty bash command>"}` | After agent-owned preparation and power-off, run the foreground cloud monitor locally, validate cloud state, and resume the same session. |
| Remote Auto Research experiment | One `remote_exec` or `download` operation | Select and prepare a campaign instance, execute the provider operation, persist its result, power off, validate local artifacts, and resume only when required. |
| Preprocessing audit | Compact `audit_report.json` written in the attempt | Validate the report after every successful direct-Codex turn; if it is missing or invalid, resume the same session so existing local or remote work can finish. |
| Other Replicate Agent outputs | Stage-owned canonical artifacts | Validate preprocessing, final codegen, cohort-refinement, plan, and per-experiment report artifacts; resume the same direct-Codex session for at most two repair turns with the exact error and owned paths. |

Initial and resumed turns in one temporary session append to the same
transcript. Explicit CLI resume preserves command artifacts but never reuses a
prior process-local session ID. Exact request/result schemas and paths are
defined in `artifacts.md`; stage completion is determined by artifact
validation, not a status field, completion sentinel, `--last`, or command exit
status alone.

Direct Codex may inspect files, edit within its stage boundary, and perform
lightweight interaction. Long-running experiments, test suites, and monitors
must be returned as one foreground operation rather than run inside the agent
turn.

## Shared information and mutation rules

- Agents treat supplied source data as read-only. Large tables are read in
  chunks or bounded batches, retaining only required columns and postponing
  global operations until compact chunk outputs are merged.
- An absent paper-required input is reported explicitly. Agents never invent,
  derive, wait for, or substitute a missing source artifact merely to continue
  the workflow.
- Secrets never enter prompts, transcripts, commands, logs, or persistent
  artifacts. Cloud-data agents may retrieve only the aggregate or declared
  result artifacts permitted below, never raw or row-level data.

## Replication agent boundaries

- Preprocessing writes claims and experiment definitions under the artifact
  contract. The executable prompt owns its paper-search procedure; the
  resulting `computational_demand` field is defined in `artifacts.md`.
- Codegen may modify only the run's copied codebase and its declared plan or
  maintenance artifacts. It inspects data through bounded, read-only reads and
  must stop on a missing required source artifact.
- Preprocessing audit treats `codegen/codebase/` and source data as read-only
  and writes only inside its attempt directory. Local-data audit never uses
  remote compute and may add an equivalent CPU, streaming, or small-batch
  adapter inside that directory without changing scientific semantics.
  Cloud-data audit reuses the existing provider state in an independent remote
  attempt, adds only audit instrumentation, and retrieves only aggregate
  statistics, logs, and the report; local CPU adapters, training, tuning, and
  evaluation are prohibited there.
- Cohort refinement may change only cohort construction, data loading,
  preprocessing, directly related data configuration, and the plan's
  `ambiguities`. It must fix and verify every reported issue. Models, training,
  tuning, evaluation, and result artifacts remain read-only. Local refinement
  never uses remote compute; cloud refinement reuses the existing instance and
  may not rent, release, reauthorize, or rematerialize data.
- A Replicate plan agent may edit the copied codebase for setup and smoke-test
  needs but may not change model semantics, introduce reduced or fallback
  plans, or hard-code paper results.
- Replication receives no paper target values by default. Smart Replicate sees
  only its claim-level audited anchors, not the paper, and records baseline,
  comparisons, hypotheses, changes, commands, and actual round results in its
  canonical log.

The exhaustive audit decision procedure, cohort-refinement routing, missing
input failure, and Smart Replicate workflow are defined in `replication.md`.

## Auto Research agent boundaries

- Experiment weighting is result-blind and runs before code inspection. The
  weighting agent reads only the paper and experiment definitions and receives
  no result artifacts. The contract agent instead treats completed replicate
  code and plans as executable truth.
- Codegen edits only the paths declared by its implementation plan and allowed
  by the experiment contract. The permitted refinement semantics and frozen
  scientific boundaries are defined in `autoresearch.md`. When a direct idea
  could materially increase computation, codegen prefers semantics-preserving
  optimizations and may declare a minimal-deviation optimized implementation
  only to avoid unreasonable resource use; it never reduces frozen experiment
  scale or required evaluation as an optimization.
- The experiment-plan agent treats the audited idea codebase as read-only,
  covers every frozen experiment at audited full scale, and maps outputs to
  frozen metrics. It receives no paper, baseline, target, or assessment-threshold
  result values.
- The experiment agent treats audited source as read-only, never reruns the
  baseline, and assumes replication intermediates are absent unless explicitly
  supplied. Deterministic preprocessing required by a refinement belongs to its
  own execution path from the fixed raw input.
- The assessment agent may judge evidence and scores but copies frozen
  experiment IDs, primary-metric names, directions, weights, and threshold
  exactly without renaming, decorating, or reinterpreting them.
- For remote experiments, the agent returns only inner foreground
  `remote_exec` Bash or a structured `download`. It never constructs SSH or
  adapter commands, manages pool membership or lifecycle, rematerializes data,
  or downloads anything except models, metrics, logs, and aggregate evidence
  within the declared artifact roots. A persisted operation or environment
  setup failure may justify a minimal environment-definition repair; changed
  hashes require successful setup validation before execution.

Eligibility, candidate-pool behavior, refinement semantics, assessment, round
routing, and campaign lifecycle are defined in `autoresearch.md`.

## Computation-provider boundary

Remote access uses the `computation-provider` skill. The selected provider
metadata and reference own resource selection, provider APIs, state validation,
and lifecycle procedures. The shared SSH helper owns provider-independent
key-first authentication, password fallback, command execution, and transfer.

Agents start with the selected reference and may consult official documentation
for bounded, non-secret diagnostics. They never guess a provider operation or
blindly repeat a billable action. A successful procedure that conflicts with
the reference is recorded in the canonical skill-correction artifact rather
than editing runtime skills during the run. Host orchestration owns plan and
artifact validation, operation execution outside agent turns, resume
reconciliation, power-off, replacement, and release as defined in
`execution.md`.
