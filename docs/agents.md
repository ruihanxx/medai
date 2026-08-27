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

- Preprocessing alone writes the complete immutable paper graph. It creates
  fine-grained D/P/T/M/V/C nodes, treats V sets as Cartesian blocks, separates
  sparse endpoints, supports P→V→C, and does not create a separate grouping
  concept. Before completion it rereads the paper for omitted study content,
  reverse-audits every dependency from C to its sources, verifies that every
  node denotes a concrete product, separates non-identical same-category
  products, and removes content outside each node category. It corrects the
  graph in place and emits no separate self-audit artifact.
- Data availability reads the graph and covers every direct D→P source boundary.
  It writes only attempt-local evidence. Orchestration owns scope derivation.
- Later agents do not edit the paper graph. They emit node-local updates in
  their existing stage artifact; orchestration assigns the source and merges
  the overlay.
- Issues have one origin node and a nonblank description. Agents never copy an
  upstream issue to descendants or create separate risk/result nodes.
- Codegen, audit/refinement attempts, replication, and each idea validation use
  distinct sources so invalidation can remove only owned updates.

## Replication boundaries

Codegen edits only the copied codebase, plan, and allowed maintenance artifacts.
It consumes only the runnable subgraph, inventories configured sources with
bounded reads and follows the persisted execution location. It stops only for
concrete unavailable direct D→P content or a measured resource constraint. It
resolves internal paper contradictions by implementing the best-supported
interpretation that preserves overall methodological consistency and records the
conflict, alternatives, rationale, evidence, and implementation location on the
exact origin node. Paper inconsistencies, unsupported mappings, and unpublished
manifests or parameters are resolved and recorded the same way, not treated as
blockers. Its `node_updates` are open and aligned to graph node IDs.

Audit treats source data and the codebase as read-only and writes only in its
attempt directory. It covers all runnable P paths and accumulates every
supported root cause. Each issue records one `node_id`, description, optional
open evidence/fix fields, and the orchestration route `preprocessing_fix` or
`source_unavailable`. Cohort refinement may change only cohort construction,
loading, preprocessing, directly related configuration, and affected P-local
updates. Model, training, validation semantics, and results remain read-only.

Planning may add setup/smoke-test code but not scientific fallback semantics.
Its steps collectively verify all runnable nodes. For every verified node, the
step description names each direct predecessor node artifact it consumes and
the concrete artifact/result it produces. Before completion the planner starts
from every runnable C, traverses to D, and checks description, artifact flow,
execution order, and outcome materialization for every visited node; it corrects
the plan in place and writes no separate self-audit artifact. Replication reads
paper text as a scientific reference, executes at full required scale, records
actual results and real evidence for every runnable node, and never modifies
source data. Smart Replicate receives only assigned claim anchors and writes
claim-specific round logs. Reporting receives one C, its real ancestors,
relevant updates/blockers, and `collect_lineage_issues(C)`; it writes one claim
fragment.

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
repairs), missing/invalid audit report, opted-in cloud materialization monitor,
Auto Research planning monitor, and one remote validation operation. Initial
and resumed turns append to one transcript. Explicit CLI resume never restores
a process-local session ID.

A successful turn alone does not complete a stage; canonical artifact validation
does. Codegen `blocked` or `failed` is immediately terminal. Base replication
may execute its planned commands within its complete agent turn. Other long
running tasks must be returned as one foreground handoff operation.

Remote access uses the metadata-selected computation-provider skill. The
provider reference owns resource selection and provider procedures; shared SSH
helpers own transport; host orchestration owns execution outside agent turns,
state validation, reconciliation, power-off, replacement, and release. Agents
may consult official provider documentation for bounded diagnostics but never
guess or blindly repeat a billable action.
