# Base Replication Workflow Contract

The canonical scientific unit is the claim-provenance graph, not a workflow
grouping. One run executes these stages:

1. Preflight records resources and maintenance artifacts.
2. PDF conversion produces audited Markdown and extracted assets.
3. Preprocessing extracts one immutable D/P/T/M/V/C paper graph. It creates a
   new node for every path-, result-, or risk-affecting difference and never
   groups nodes into a separate canonical unit.
4. Data availability covers every direct D→P source boundary exactly once.
   Orchestration propagates unavailable or unknown requirements forward and
   writes the hash-bound maximal claim scope.
5. The PARTIAL gate records a scope-bound decision and proceeds by default.
   NONE or an explicitly rejected PARTIAL stops before mutation or billable
   execution.
6. Codegen consumes only the runnable subgraph, inspects sources read-only, and
   writes code plus node-local updates. Missing required input stops explicitly.
7. Audit checks all runnable preprocessing paths. Each issue has one origin
   node and routes either to preprocessing refinement or source availability.
8. At most three cohort-refinement rounds may change only P-related code and
   node updates; M, training, evaluation, and results remain read-only.
9. Planning writes one node-free environment/setup step followed by one step
   per earliest runnable-DAG topological layer. Each runnable node appears in
   exactly one layer step via `verifies`, without fallback scale.
10. Replication executes the plan and supplies actual result/evidence updates
    for every runnable node.
11. Smart Replicate, when enabled, checkpoints only runnable claims having a
    paper result under `replication/claims/<claim_id>/`.
12. Reporting checkpoints each C independently, collects only its actual
    ancestors' issues, and composes the final report in paper-graph order.

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

Audit FAIL with preprocessing defects enters refinement. `source_unavailable`
returns to availability without consuming a refinement. A new scope invalidates
all downstream scope-bound stages. The fourth complete FAIL continues to
planning with every issue and the exhaustion state retained. Audit accumulates
all supported root causes; it does not stop at the first finding.

Replication receives no paper target values by default. Smart Replicate adds
only each assigned C's paper anchor and permits at most five hypothesis-driven
rounds. Each round records observed result, comparison, hypothesis, exact
changes, commands, new result, and conclusion. It reruns only paths affected by
its change. Hard-coding anchors or editing computed output is prohibited.

`manifest.json` v6 owns stages, attempts, outputs, checkpoints, and the immutable
input fingerprint. A skipped completed stage first reloads and validates its
artifacts. Reporting stores `completed_claims` in graph order. Reopening a fully
completed run is a validation-only no-op.
On resume, a v6 scope checkpoint written with the removed global `UNKNOWN`
verdict is deterministically rederived from its unchanged availability report
as `PARTIAL` or `NONE` and its checkpoint is migrated before execution.

If explicit resume occurs after replication starts but before the final report,
replication/report artifacts and cited outputs are archived under
`resume_history/resume_<NNN>/`; old `replicate_agent` overlay updates are
removed; replication restarts from plan step 1. Infrastructure replacement
before replication invalidates codegen and downstream stages while retaining
the prepared codebase. Remote lifecycle and partial exit codes are defined in
`execution.md`.

Manifest v1–v5 is historical and disk-read-only. Loading it for resume or as an
Auto Research base fails before any write and instructs the operator to use a
new output directory.
