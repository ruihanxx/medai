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
      "description": "construct P1 from D1 and persist audit evidence",
      "command_hint": "python ...",
      "expected_outcome": "real artifact and checks",
      "verifies": ["D1", "P1"]
    }
  ],
  "remote_compute": null
}
```

Use 3–10 steps with unique sequential IDs. `command_hint` must be a concrete
foreground command or a precise command construction instruction. If remote
compute is required, copy the existing remote fields from the validated
codegen plan; never invent another instance. Reload the JSON and cross-check
the verifies union against the exact runnable ID list before finishing.
