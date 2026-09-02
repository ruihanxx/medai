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
- `source_blocked` only when complete relevant source inspection demonstrates
  that the required underlying content is absent;
- `unknown` only when source inspection itself cannot determine availability,
  for example because the source is inaccessible or unreadable, its inventory
  or metadata is incomplete, or the probe is inconclusive.

Treat later source-revision reports as evidence to investigate, not as source
status decisions. Reinspect the complete relevant inventory of configured
sources before changing a prior decision. Paper omissions, ambiguous scientific
definitions, unspecified thresholds or coding rules, unsupported field or
category mappings, and multiple defensible operationalizations are preprocessing
decisions. Do not include the missing decision itself in `required_content`, and
do not use any of these conditions by itself to assign either `source_blocked`
or `unknown`. When the configured source contains underlying observations that
support a defensible operationalization, assign `available` and record the
ambiguity and methodological risk in `evidence`. A narrower source inspection
cannot replace a broader one.

Do not use `source_blocked` solely for a dataset or terminology version
mismatch: when a configured source contains the corresponding content in
another version, mark it `available`, record both versions and the
methodological risk in `evidence`, and do not claim equivalence.

An available entry must set `source_kind` and `source_name` to one of the exact
configured sources. A non-available entry may use null source fields. Preserve
the distinction between unavailable and uncertain.

The host has already validated the selected provider and drive configuration
against their metadata before invoking this stage. Do not inspect a stage-local
`.env`, use `env`, `printenv`, or shell variable tests, or guess or reconstruct
any provider environment variable name. A missing computation-provider state
means that no instance has been acquired yet; it does not show that provider
configuration is missing.

Choose `execution_location` as `local`, `remote`, or null. Use null only when no
runnable location can yet be established. Consider the paper's intended scale,
`{{ resources_path }}`, and configured providers. If remote inspection is
needed, determine provider readiness only by invoking the adapter selected in
provider metadata and following `{{ computation_provider_reference }}` and
`{{ drive_reference }}`. Use the current state at
`{{ computation_provider_state_path }}` when it exists; otherwise follow the
adapter's documented search and create procedure. Only an actual adapter failure
may support a claim that the provider is unavailable. Store its non-secret
failure evidence under `{{ results_dir }}`. Never copy restricted row-level data
into the run.

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
