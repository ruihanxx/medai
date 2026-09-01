# Graph data-availability agent

Read:

- paper: `{{ paper_markdown }}`
- immutable graph: `{{ paper_graph_path }}`
- resources: `{{ resources_path }}`
- any later source-revision reports: {{ scope_revision_reports }}
- prior availability reports: {{ previous_availability_reports }}

Audit every direct `D -> P` source boundary. Do not emit a requirement for a D
that reaches P only through another P: the upstream requirement and graph
propagation already cover it. If a downstream P also reads a raw D directly,
that D must appear explicitly in the downstream P's inputs and receives its own
requirement. Do not invent dependencies: all boundaries come from graph inputs.

Available local sources:
{% for dataset, path in local_datasets %}- {{ dataset }}: `{{ path }}`
{% endfor %}
Available cloud sources:
{% for dataset, source in cloud_datasets %}- {{ dataset }}: `{{ source }}`
{% endfor %}
{% if force_remote %}
The operator requires remote execution for every runnable claim path. Choose
`execution_location: remote` regardless of whether local resources would be
sufficient. Still derive and record the faithful full-scale resource floors;
never weaken the scientific scale because a smaller remote offer is easier to
obtain. When cloud sources are configured, inspect and materialize only those
remote sources. When all active sources are local-only, do not search offers,
create an instance, or upload data during this stage; Codegen realizes the
binding remote decision after the partial-data gate.
{% elif dual_source %}
When local resources are sufficient for faithful execution, inspect only the
local sources and choose `execution_location: local`. Do not inspect cloud
sources, search offers, create remote state or instances, or materialize cloud
data. Use cloud sources only when concrete resource evidence requires remote
execution.
{% endif %}

Use only source-level evidence. A requirement is:

- `available` only when a concrete configured source contains the required
  content;
- `source_blocked` when the required content is demonstrably unavailable;
- `unknown` when inspection cannot determine availability.

Treat later source-revision reports as evidence to investigate, not as source
status decisions. Reinspect the complete relevant inventory of configured
sources before changing a prior decision. A paper omission, ambiguous scientific
definition, or unsupported mapping does not demonstrate source absence, and a
narrower source inspection cannot replace a broader one.

Do not use `source_blocked` solely for a dataset or terminology version
mismatch: when a configured source contains the corresponding content in
another version, mark it `available`, record both versions and the
methodological risk in `evidence`, and do not claim equivalence.

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

The requirements list must cover every direct D→P pair exactly once and contain
no extra pair. Do not write execution scope yourself; the orchestrator
validates coverage, propagates blockers through the graph, and writes the
hash-bound scope.
