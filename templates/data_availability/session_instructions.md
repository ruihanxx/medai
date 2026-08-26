# Graph data-availability agent

Read:

- paper: `{{ paper_markdown }}`
- immutable graph: `{{ paper_graph_path }}`
- resources: `{{ resources_path }}`
- any later source-revision reports: {{ scope_revision_reports }}

Audit every requirement formed by one P node and each upstream D node feeding
that P. Two P nodes using the same D are separate requirements, even when they
differ only by cohort construction, label, split, or preprocessing detail.
Do not invent dependencies: all dependencies already come from graph inputs.

Available local sources:
{% for dataset, path in local_datasets %}- {{ dataset }}: `{{ path }}`
{% endfor %}
Available cloud sources:
{% for dataset, source in cloud_datasets %}- {{ dataset }}: `{{ source }}`
{% endfor %}

Use only source-level evidence. A requirement is:

- `available` only when a concrete configured source contains the required
  content;
- `source_blocked` when the required content is demonstrably unavailable;
- `unknown` when inspection cannot determine availability.

An available entry must set `source_kind` and `source_name` to one of the exact
configured sources. A non-available entry may use null source fields. Preserve
the distinction between unavailable and uncertain.

Choose `execution_location` as `local`, `remote`, or null. Use null only when no
runnable location can yet be established. Consider the paper's intended scale,
`{{ resources_path }}`, and configured providers. If remote inspection is
needed, follow `{{ computation_provider_reference }}` and
`{{ drive_reference }}` using the existing state at
`{{ computation_provider_state_path }}`. Store probe evidence under
`{{ results_dir }}` and never copy restricted row-level data into the run.

Write `{{ report_path }}`:

```json
{
  "capacity_decision": {
    "execution_location": "local",
    "rationale": "evidence-bound rationale"
  },
  "requirements": [
    {
      "preprocessing_id": "P1",
      "dataset_id": "D1",
      "source_kind": "local",
      "source_name": "/configured/source",
      "required_content": "exact data/cohort fields needed by P1",
      "status": "available",
      "evidence": "what was inspected and found"
    }
  ]
}
```

The requirements list must cover every P×upstream-D pair exactly once and must
contain no extra pair. Do not write execution scope yourself; the orchestrator
validates coverage, propagates blockers through the graph, and writes the
hash-bound scope.
