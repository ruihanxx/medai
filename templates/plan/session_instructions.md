# Runnable graph replication planner

Create an executable plan for the exact runnable claim subgraph.

Read:

- codebase: `{{ codebase_dir }}`
- paper: `{{ paper_markdown }}`
- graph: `{{ paper_graph_path }}`
- scope: `{{ execution_scope_path }}`
- available data: {{ data_paths }}
- resources/GPU: {{ gpu_info }}

The immutable graph payload is:

```json
{{ paper_graph | tojson(indent=2) }}
```

The plan must cover these node IDs exactly once or more across all `verifies`
lists; no inactive ID is allowed:

```json
{{ runnable_node_ids | tojson(indent=2) }}
```

Plan dependency-ordered execution across D/P/T/M/V/C. A setup-only step may
have an empty `verifies`, but the union of all nonempty lists must equal every
runnable node. Make P intermediates auditable, produce each unique M artifact,
and expand every V's model/data/metric Cartesian product. Statistical paths may
go directly from P to V. Do not combine nodes merely to shorten the plan.

For every node named in a step's `verifies`, that step's `description` must
contain a separate, concrete node clause of this form:

```text
For <node_id>, consume <each direct input node ID and its concrete artifact or
planned artifact path>; perform <the node-local graph method>; produce
<the concrete artifact/result and its path or result shape>.
```

Name every direct input from the graph; do not write only "use upstream
outputs." This direct-input chain must account for every transitive ancestor of
the node. If a command directly reads a transitive ancestor rather than only its
declared direct inputs, name that artifact too and correct the graph if the read
is a genuine undeclared dependency. For a source D with no inputs, identify the
exact source artifact being validated or read. If one step verifies several
nodes, include one clause for each node in dependency order. The
`expected_outcome` must identify the persistent artifact, execution record, or
result block produced for every verified node so later steps can consume it.

In particular, describe P as consuming its D/P artifacts, T as consuming all
P/prior-M artifacts, M as the concrete artifact produced by T, V as consuming
all evaluated M/P_eval artifacts and producing its metric/statistical result,
and C as consuming every supporting V result artifact and producing the
claim-level reproduced result. A node ID appearing only in `verifies` but not
in the description's artifact flow is not planned.

Inspect actual entry points and dependencies in the codebase. Use paper-scale
data, epochs, grids, resampling, and hardware. Do not substitute toy data,
smaller models, fewer epochs, or reported results. Include output-producing
steps for all runnable claims and their ancestors, plus evidence collection and
environment capture.

{% if cloud_drive_enabled %}
Read `{{ computation_provider_reference }}` and
`{{ drive_reference }}`. Reuse the run-owned state at
`{{ computation_provider_state_path }}`. Keep raw cloud data remote and plan
local download only for non-sensitive result/evidence artifacts.
{% endif %}

Write `{{ replicate_plan_path }}`:

```json
{
  "environment": {
    "language": "Python 3.12",
    "key_dependencies": ["package==version"],
    "setup_hints": "reproducible setup"
  },
  "steps": [
    {
      "id": 1,
      "description": "For D1, read and identify source artifact /data/d1. For P1, consume D1 artifact /data/d1, apply P1.method, and produce P1 cohort artifact outputs/p1.parquet.",
      "command_hint": "python ...",
      "expected_outcome": "D1 source identity evidence and P1 artifact outputs/p1.parquet with audit checks",
      "verifies": ["D1", "P1"]
    }
  ],
  "remote_compute": null
}
```

Use 3–10 steps with unique sequential IDs. `command_hint` must be a concrete
foreground command or a precise command construction instruction. If remote
compute is required, copy the existing remote fields from the validated
codegen plan; never invent another instance.

## Mandatory reverse plan self-audit

Do not finish after drafting the steps. Reload the paper graph, runnable scope,
and plan, then start separately from every runnable terminal C and walk its
`inputs` backwards to the source D nodes. For every visited node, verify all of
the following:

1. At least one step includes the node in `verifies` and explicitly describes
   the node-local operation and concrete output artifact/result.
2. The description names every direct predecessor node ID and the exact
   predecessor artifact consumed. For C this includes every supporting V result;
   for V every evaluated M and P_eval artifact; for M its producing T record;
   for T every P and prior-M artifact; and for P every direct D/P artifact.
3. Every predecessor artifact is produced or identified by an earlier clause or
   earlier step. When producer and consumer share a step, their clauses and
   command behavior are ordered producer first.
4. The planned command actually consumes those artifacts rather than merely
   mentioning their node IDs, and its expected outcome materializes what every
   downstream consumer needs.
5. The description does not introduce an inactive node, paper result as an
   input, undeclared dependency, fallback artifact, or relevance-only edge.

Maintain this reverse checklist internally; do not create another artifact.
Correct missing descriptions, artifact paths, dependencies, ordering, commands,
or outcomes, then rerun the affected C-to-D traversal. Finally cross-check that
the `verifies` union equals the exact runnable ID list and finish only when every
runnable C path passes both artifact-flow and structural coverage checks.
