# Agent, Prompt, and Skill Boundary Contract

Generic replication prompts live under `templates/<stage>/`, Auto Research
prompts under `templates/autoresearch/<stage>/`, and runtime skills under
`templates/skills/`. Prompts are rendered with strict Jinja context and
persisted before invocation. Every provider event stream is kept as JSONL; a
transcript is diagnostic evidence, never a structured result.

Generic prompts remain provider- and dataset-agnostic. Provider APIs,
credentials, schemas, and recovery procedures belong only to selected skill
references or adapters. Secrets never enter prompts, transcripts, commands,
logs, manifests, or reports. Source data is read-only; agents retain only
needed columns/aggregates and never substitute a missing paper-required input.

## Graph ownership

- Repository discovery runs after PDF conversion and reads only paper Markdown.
  It emits exact verbatim Git URLs and evidence, never browses or follows DOI,
  OSF, Zenodo, publisher, or ordinary landing pages, and receives no local-repo
  environment hint. Orchestration alone validates and acquires repositories.
- Preprocessing alone writes the complete immutable paper graph. It creates
  fine-grained D/P/T/M/V/C nodes, treats V sets as Cartesian blocks, separates
  sparse endpoints, supports P→V→C, and does not create a separate grouping
  concept. It reconstructs the executable analysis from the full paper,
  inventories concrete states and their set/derivation relations, then creates
  edges only for actual producer-consumer dependencies; figures are supporting
  evidence, and set containment alone is not a dependency. Before completion it
  rereads the paper for omitted study content,
  reverse-audits every dependency from C to its sources, verifies that every
  node denotes a concrete product, separates non-identical same-category
  products, and removes content outside each node category. It corrects the
  graph in place and emits no separate self-audit artifact.
- Data availability reads the graph and covers every direct D→P source boundary.
  It writes only attempt-local evidence. A dataset or terminology version
  mismatch alone remains available when corresponding content exists, with both
  versions and the methodological risk recorded without claiming equivalence.
  Later source-revision reports are evidence to investigate, not availability
  decisions. Paper omissions, ambiguous definitions, unspecified coding, and
  unsupported mappings are preprocessing decisions and cannot by themselves
  produce either `source_blocked` or `unknown`; `unknown` is reserved for
  inconclusive inspection of the source itself. A narrower inspection cannot
  replace a broader one. The host validates selected provider and drive
  configuration against metadata before invocation. Availability does not
  inspect `.env`, hand-check or infer environment-variable names, or treat a
  missing instance state as missing configuration. When remote inspection is
  required, provider readiness is established only through the metadata-selected
  adapter; a provider-unavailable finding requires non-secret evidence from an
  actual adapter failure.
  Orchestration owns scope derivation.
- Later agents do not edit the paper graph. They emit node-local updates in
  their existing stage artifact; orchestration assigns the source and merges
  the overlay.
- Issues have one origin node and a nonblank description. Agents never copy an
  upstream issue to descendants or create separate risk/result nodes.
- Codegen, audit/refinement attempts, replication, and each idea validation use
  distinct sources so invalidation can remove only owned updates.

## Replication boundaries

Codegen always starts in an empty generated-code directory and edits only that
codebase, plan, and allowed maintenance artifacts. It never receives repository
inventory, paths, contents, or `MEDAI_HOST_REPO`; it may not inspect sibling
snapshots or browse a disclosed repository URL. `--repo` is not seed code.
It consumes only the runnable subgraph, inventories configured sources with
bounded reads and follows the persisted execution location. It stops only for
concrete unavailable direct D→P content or a measured resource constraint. It
resolves internal paper contradictions by implementing the best-supported
interpretation that preserves overall methodological consistency and records the
conflict, alternatives, rationale, evidence, and implementation location on the
exact origin node. Paper inconsistencies, unsupported mappings, and unpublished
manifests or parameters are resolved and recorded the same way, not treated as
blockers. Its `node_updates` are open and aligned to graph node IDs.

Repository calibration runs only when a frozen snapshot is available. It may
read bounded text source/configuration but must never run, import, compile,
install, source, deserialize, or invoke repository content. Its first pass
inventories every paper-related cohort, preprocessing, model, training,
hyperparameter, and validation semantic across the complete graph, including
hidden details codegen already matched; its second pass compares those points
with independent codegen. Each point has one origin node. Only runnable points
may change code, and all edits are developed in a candidate copy before exact
delta validation and promotion. Repository behavior is normally adopted when
paper-supported, paper-unspecified, or paper-contradictory (the contradiction
remains explicit). Unresolved inter-repository conflicts, inactive paths,
literal result hardcoding, outcome-guided selection, and leakage are recorded
with `adopt=false`. Repository snapshots and calibration baselines are immutable.

Audit treats source data and the codebase as read-only and writes only in its
attempt directory. It covers all runnable P paths and accumulates every
supported root cause. Each issue records one `node_id`, description,
evidence-bound diagnosis, observable required correction outcome, and the
orchestration route `preprocessing_fix` or `source_unavailable`; audit defines
the required outcome, not its implementation. `source_unavailable` requires new
source evidence at least as broad as the approved availability evidence; paper
omissions and ambiguous mappings remain preprocessing decisions. Cohort
refinement confirms each diagnosis against baseline evidence, chooses the
correction, and may change only cohort construction, loading, preprocessing,
directly related configuration, and affected P-local updates. It creates
attempt-local baseline and candidate copies while retaining the authoritative
code unchanged, develops each fix only in the candidate, compares candidate
and baseline cohort semantics across
affected and shared P paths, and promotes only a patch whose every delta is
required by a reported root cause or is an unavoidable paper-consistent
consequence.
Unrelated or paper-contradictory deltas require another candidate revision.
Model, training, validation semantics, and results remain read-only.
Cohort refinement treats graph `paper_result` values only as observed reference
outputs: they cannot become runtime assertions, reconciliation gates, success
criteria, or exception conditions. Computed discrepancies remain explicit in
audit metadata and downstream evidence; only source, method, schema, and
artifact-integrity conditions may fail preprocessing.

Planning may add setup/smoke-test code but not scientific fallback semantics.
It emits one node-free setup step, then one step per host-supplied earliest DAG
topological layer; layers cannot be merged, split, or reordered. Its steps
collectively verify every runnable node exactly once. For every verified node, the
step description names each direct predecessor node artifact it consumes and
the concrete artifact/result it produces. Before completion the planner starts
from every runnable C, traverses to D, and checks description, artifact flow,
execution order, and outcome materialization for every visited node; it corrects
the plan in place and writes no separate self-audit artifact. Replication reads
paper text as a scientific reference, executes at full required scale, records
actual results and real evidence for every runnable node, and never modifies
source data. On resume it consumes the host-validated completed/pending node
partition, rechecks completed artifact shape before use, skips completed nodes,
and executes pending nodes in plan-layer order. The graph node, not an internal
phase of a long command, is the orchestration resume boundary. Smart Replicate
receives only assigned claim anchors and writes claim-specific round logs.
Per-claim reporting receives one C, its real ancestors, relevant
updates/blockers, and `collect_lineage_issues(C)`; it writes one claim fragment.
After all fragments complete, the final report agent reads the paper,
graph-ordered claim index, complete node issue index, fragments, and real
replication outputs. It copies claim assessments unchanged and writes only the
four report index tables plus the final repository-calibration section defined
in `artifacts.md`; it does not redo a claim's scientific judgment or propagate
issues to descendants.

## Auto Research boundaries

The weighting agent is result-blind and reads only paper/paper graph. It lists
every eligible prediction V, including zero-weight Vs. The contract agent uses
the completed base code and artifacts and writes contracts only for positive Vs.

Idea codegen changes only declared files allowed by contracts and creates new
P/T/M/V nodes for changed semantics; base nodes are immutable. Audit checks are
freely named but must evidence every positive V and prove refinement-only scope.
The validation planner and runner never rerun the baseline. They cover each
refined V and its Cartesian endpoints, treat audited source as read-only, and
write actual/evidence updates for all new nodes. Assessment copies frozen V IDs,
metrics, rules, weights, and threshold exactly.

Remote validation agents return only one inner foreground `remote_exec` or a
structured confined `download`. They never construct SSH/adapter commands,
manage pool membership or lifecycle, rematerialize raw data, or download
anything outside declared model/metric/log/aggregate roots.

## Invocation handoffs

One-turn invocation is the default. Direct Codex may keep one temporary session
across these orchestration handoffs: invalid final stage artifacts (at most two
repairs), missing/invalid audit report, opted-in data-availability provider
and remote-inspection commands, codegen cloud-materialization commands, Auto
Research cloud-materialization monitors, and one remote validation operation.
Initial and resumed turns append to one transcript. Explicit CLI resume never
restores a process-local session ID.

A successful turn alone does not complete a stage; canonical artifact validation
does. Codegen `blocked` or `failed` is immediately terminal. Base replication
may execute its planned commands within its complete agent turn. Other long
running tasks must be returned as one foreground handoff operation. A Codex
process that exits successfully while its transcript still contains an
unfinished command execution is rejected rather than treated as a completed
turn.

Within Codegen and base Replication turns, command execution is serial. A
running execution handle blocks every new command, file edit, check, and
terminal result until the agent polls that handle to a terminal event or
explicitly terminates it and waits for the terminal event. Neither agent leaves
more than one command execution running.

Data availability may run only provider search, status, and state validation
inside its agent turn. Every remote-execution action is a single foreground
handoff; checks over the same remote source are combined, and no replacement is
started before the prior command reaches a terminal state.

Before cloud materialization completes, Codegen may run only bounded read-only
provider diagnostics inside its agent turn. Every cloud-materialization action,
including preparation and monitoring, is a single foreground handoff. The agent
rereads canonical state only after orchestration resumes it from the prior
command's terminal result.

Remote access uses the metadata-selected computation-provider skill. The
provider reference owns resource selection and provider procedures; shared SSH
helpers own transport; host orchestration owns execution outside agent turns,
state validation, reconciliation, power-off, replacement, and release. Agents
may consult official provider documentation for bounded diagnostics but never
guess or blindly repeat a billable action.
