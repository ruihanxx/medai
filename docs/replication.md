# Base Replication Workflow Contract

The canonical scientific unit is the claim-provenance graph, not a workflow
grouping. One run executes these stages:

1. PDF conversion produces audited Markdown and extracted assets.
2. Preflight records resources and maintenance artifacts, extracts only Git
   URLs directly disclosed in that Markdown, and freezes available public
   repositories as source snapshots. Acquisition failures are recorded and do
   not block replication.
3. Preprocessing extracts one immutable D/P/T/M/V/C paper graph. It creates a
   new node for every path-, result-, or risk-affecting difference and never
   groups nodes into a separate canonical unit.
4. Data availability covers every direct D→P source boundary exactly once.
   Orchestration propagates unavailable or unknown requirements forward and
   writes the hash-bound maximal claim scope. For an opted-in direct Codex cloud
   source, state-changing provider commands run as foreground orchestration
   handoffs between turns of the same temporary availability session.
5. The PARTIAL gate records a scope-bound decision and proceeds by default only
   when its runnable subgraph uses at least one confirmed source. NONE, a scope
   without an active source, or an explicitly rejected PARTIAL stops before
   mutation or billable execution.
6. Codegen starts from an empty generated-code directory, consumes only the
   runnable subgraph and supplied data, and receives no repository inventory,
   path, content, or repository environment hint.
7. When at least one snapshot is available, repository calibration statically
   compares all paper-related repository paths with the complete graph, paper,
   and independent codegen. It records every omission/conflict and promotes
   only verified runnable-scope candidate deltas mapped to `adopt=true`.
8. Audit checks all runnable preprocessing paths. Each issue has one origin
   node and routes either to preprocessing refinement or source availability.
9. At most three cohort-refinement rounds may change only P-related code and
   node updates. Each round follows the
   [candidate-copy semantic-delta review](agents.md#replication-boundaries)
   before promotion; M, training, evaluation, and results remain read-only.
10. Planning writes one node-free environment/setup step followed by one step
   per earliest runnable-DAG topological layer. Each runnable node appears in
   exactly one layer step via `verifies`, without fallback scale.
11. Replication executes the plan and supplies actual result/evidence updates
    for every runnable node.
12. Smart Replicate, when enabled, checkpoints only runnable claims having a
    paper result under `replication/claims/<claim_id>/`.
13. Reporting checkpoints each C independently and collects only its actual
    ancestors' issues. A final report agent then indexes the completed fragments,
    named paper artifacts, claim paths, and origin-local node issues into the
    four core tables plus the repository-calibration section defined in
    `artifacts.md`.

All graph inputs are AND dependencies. Availability blocking therefore flows
through every downstream consumer. The final scope verdict is claim-based:
`FULL` means every C is runnable, `PARTIAL` means some but not all Cs are
runnable, and `NONE` means no C is runnable. An unavailable or unknown
requirement blocks only its dependent claims. Runnable IDs contain the union of
each runnable C and its ancestors; unrelated available nodes are not executed.

Paper graph content never changes after preprocessing. Stage findings are
merged into `graph/node_state.json` using stage-owned sources. An issue is never
copied into descendants. Audit attempts and refinement attempts keep distinct
sources. Scope or stage invalidation removes only owned updates.

Direct Codex completion is artifact-driven. Preprocessing, codegen, audit,
refinement, planning, replication, and per-claim reporting may resume the same
temporary session for at most two repair turns when their final artifact is
missing or invalid. A structured codegen `blocked` or `failed` result is
terminal and does not consume artifact-repair turns. Other providers retain
one-turn behavior. A technical retry does not consume a scientific audit or
refinement attempt.

Audit FAIL with preprocessing defects enters refinement while rounds remain,
including a mixed report that also contains `source_unavailable`. A source-only
FAIL, or a mixed FAIL after refinement exhaustion, returns to availability. A
new scope invalidates all downstream scope-bound stages. The fourth complete
FAIL without a source issue continues to planning with every issue and the
exhaustion state retained. Audit accumulates all supported root causes; it does
not stop at the first finding.

Replication receives no paper target values by default. Smart Replicate adds
only each assigned C's paper anchor and permits at most five hypothesis-driven
rounds. Each round records observed result, comparison, hypothesis, exact
changes, commands, new result, and conclusion. It reruns only paths affected by
its change. Hard-coding anchors or editing computed output is prohibited.

`manifest.json` v7 owns stages, attempts, outputs, checkpoints, and the immutable
input fingerprint. A skipped completed stage first reloads and validates its
artifacts. Reporting stores `completed_claims` in graph order. Reopening a fully
completed run is a validation-only no-op, except that a report completed before
the final report transcript was introduced reuses all validated claim fragments
and runs only the final indexing agent once.

If explicit resume occurs after replication starts but before the final report,
replication/report artifacts and cited outputs are snapshotted under
`resume_history/resume_<NNN>/` without clearing the canonical attempt. The host
checks every current or archived node update, its real evidence and generic
JSON/gzip integrity, and predecessor closure. Valid archived evidence is
restored atomically when needed. Replication then follows the plan from the
first layer while executing only pending nodes; completed nodes are reused, not
rerun. The `replicate_agent` manifest checkpoint records the inspected
`completed_node_ids` for that attempt. A legacy non-layered plan is regenerated while recovered node results
remain eligible. Node completion is the resume boundary; this contract does not
define long-node internal checkpoints. Infrastructure replacement before
replication invalidates codegen and downstream stages while retaining the
prepared codebase. Remote lifecycle and partial exit codes are defined in
`execution.md`.

Manifest v1–v6 is historical and disk-read-only. Loading it for resume or as an
Auto Research base fails before any write and instructs the operator to use a
new output directory.
