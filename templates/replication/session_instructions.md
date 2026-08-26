# Claim-graph replication executor

Execute the complete plan and produce real, node-aligned evidence. Do not edit
the immutable graph or orchestration-owned node state.

Read:

- plan: `{{ replicate_plan_path }}`
- paper: `{{ paper_markdown }}`
- graph: `{{ paper_graph_path }}`
- scope: `{{ execution_scope_path }}`
- current overlay (read-only): `{{ node_state_path }}`
- codebase: `{{ codebase_dir }}`

Work in `{{ codebase_dir }}` and write canonical run artifacts under
`{{ replication_dir }}`. Execute every plan step in order, in the foreground.
Diagnose and fix environment/API/source defects when scientifically safe, log
each fix and its cause, and continue. Never use paper results as computed output,
silently alter cohort/model semantics, cherry-pick seeds, or downsize for speed.

Run at the intended scale. If an actual resource limit forces a deviation,
first record measured resources, make the efficient full-scale path work where
possible, then describe the exact deviation and affected node IDs. Sanity-check
each P/T/M intermediate before consuming it downstream. Expand all cells in a
V block's model/data/metric Cartesian product.

{% if cloud_drive_enabled %}
Read `{{ computation_provider_reference }}` and `{{ drive_reference }}`. Reuse
the existing state at `{{ computation_provider_state_path }}` and the plan's
remote directories. Verify every selected cloud drive before execution. Keep
raw/row-level data remote; download only result, log, status, and aggregate
evidence artifacts. Do not release or power off the instance—the workflow owns
that action after artifact validation.
{% endif %}

## Canonical artifacts

Update `{{ replication_dir }}/replication_log.json` after every completed step:

```json
{
  "step_outcomes": [
    {
      "step_id": 1,
      "description": "what ran",
      "command_executed": "actual command",
      "exit_code": 0,
      "stdout": "bounded stdout",
      "stderr": "bounded stderr",
      "output_files": ["real/local/result.json"],
      "duration_seconds": 12.5,
      "fixes_applied": [
        {
          "file_path": "src/file.py",
          "description": "change and reason",
          "original_error": "triggering error",
          "diff_snippet": "before/after"
        }
      ],
      "code_modified": true,
      "notes": "scientific and execution observations"
    }
  ],
  "node_updates": [
    {
      "node_id": "P1",
      "result": {"rows": 1234, "split": "persisted"},
      "evidence": ["real/local/p1_summary.json"],
      "issues": [{"description": "local uncertainty or failure", "evidence": ["..."]}]
    },
    {
      "node_id": "C1",
      "result": "actual conclusion derived from upstream validation",
      "evidence": ["real/local/claim_c1.json"],
      "issues": []
    }
  ]
}
```

The node update list must cover every `runnable_node_id` exactly once. Every
update must have a nonempty actual `result` and at least one existing local
`evidence` path under the codebase or replication directory. A result may be a
number, object, text observation, or artifact description. Do not cite the
replication log or environment summary as node evidence. Keep issues local to
their origin node; do not copy upstream issues downstream. The orchestrator
assigns source `replicate_agent` and merges these updates after validation.

Every plan step with a nonempty `verifies` list must cite at least one existing
output file. Attribute outputs to the step that scientifically produced them,
including after remote downloads.

Write `{{ replication_dir }}/evidence_summary.json`:

```json
{
  "environment": {
    "python_version": "3.12.x",
    "gpu_available": true,
    "gpu_model": "NVIDIA ...",
    "key_packages": {"numpy": "2.x"}
  }
}
```

Add other environment fields when useful.

{% if smart %}
## Claim-level Smart Replicate

Only these runnable claims have explicit paper results:

```json
{{ smart_anchors }}
```

Run the complete baseline once before consulting a paper result as a tuning
signal. For each listed claim, compare actual and paper result, then test at
most five scientifically defensible methodological hypotheses. Rerun only paths
affected by each modification; do not rerun unaffected shared ancestors. Never
hard-code a result, tune arbitrary constants, cherry-pick, or hide divergence.

Write one log at
`{{ replication_dir }}/claims/<claim_id>/smart_replicate_log.json`:

```json
{
  "claim_id": "C1",
  "baseline_result": "actual baseline",
  "paper_result": "paper anchor",
  "rounds": [
    {
      "round": 1,
      "observed_result": "before",
      "anchor_comparison": "quantified discrepancy",
      "hypothesis": "testable methodological explanation",
      "changes": ["exact justified change and affected nodes"],
      "commands": ["actual rerun command"],
      "result_after_change": "actual output",
      "conclusion": "supported/rejected/inconclusive"
    }
  ],
  "final_result": "result represented in node updates"
}
```
{% endif %}

Use applicable skills from `{{ skills_dir }}` when their descriptions match.
Before ending, complete all plan steps, reload both canonical JSON files, verify
all evidence paths exist locally, and ensure node update coverage is exact. A
resumed repair turn should preserve valid completed work and repair only the
reported artifact defect.
