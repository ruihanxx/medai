# Runnable graph scientific audit

Audit the generated implementation and its preprocessing outputs against the
paper. Do not edit the immutable graph or generated code.

Read:

- paper: `{{ paper_markdown }}`
- paper graph: `{{ paper_graph_path }}`
- approved scope: `{{ execution_scope_path }}`
- codegen plan: `{{ codegen_plan_path }}`
- codebase: `{{ codebase_dir }}`
- resources: `{{ resources_path }}`

Audit every runnable P node and every direct D→P source requirement, plus any T/M/V
implementation whose correctness depends on those outputs. Distinct P nodes
must be checked separately even when they share a D. Check exact source mapping,
cohort construction, exclusions, linkage, label semantics, split leakage,
preprocessing order, units, missing values, feature construction, and the
observable counts/distributions needed to support downstream nodes. For V,
check that its declared model/data/metric sets will execute as a complete
Cartesian product.

Run small diagnostic/audit scripts from `{{ scripts_dir }}` and store local
evidence under `{{ results_dir }}`. These checks may inspect structure and
intermediate values but must not replace the full replication. Keep raw sources
read-only and never copy restricted row-level content into audit artifacts.

{% if cloud_drive_enabled %}
For remote checks, follow `{{ computation_provider_reference }}` and
`{{ drive_reference }}`, reuse `{{ remote_compute_state_path }}`, work under
`{{ remote_audit_dir }}`, and download only non-sensitive summaries/evidence.
{% endif %}

Each issue has exactly one origin `node_id`. Do not attach the same issue to all
descendants; lineage propagation is computed later. Add any paper-specific
fields that improve the audit. `route` is the only orchestration field and must
be either:

- `preprocessing_fix` when generated preprocessing/cohort logic should be
  refined;
- `source_unavailable` only when concrete evidence proves an approved source
  cannot supply a required direct D→P input.

Write `{{ report_path }}`:

```json
{
  "verdict": "FAIL",
  "issues": [
    {
      "node_id": "P1",
      "description": "the implemented exclusion omits the paper's age filter",
      "route": "preprocessing_fix",
      "evidence": ["results/cohort_counts.json", "paper Methods"],
      "required_fix": "apply the stated filter before splitting"
    }
  ]
}
```

PASS requires an empty issue list. FAIL requires at least one issue. Every issue
must use a runnable node ID and a nonblank description. Do not use fixed kind or
severity taxonomies. Finish only after the JSON is valid and all cited evidence
exists.
