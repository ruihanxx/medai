# Claim report agent

Write one evidence-bound fragment for claim `{{ claim_id }}` to
`{{ claim_report_path }}`. Do not edit another claim fragment or the combined
report; orchestration composes fragments deterministically in graph order.

Read:

- claim node:

```json
{{ claim_json }}
```

- paper and assets: `{{ paper_markdown }}`, `{{ paper_artifacts }}`
- full graph and overlay: `{{ paper_graph_path }}`, `{{ node_state_path }}`
- scope: `{{ execution_scope_path }}`
- plan/log/environment: `{{ replicate_plan_path }}`,
  `{{ replication_log_path }}`, `{{ evidence_summary_path }}`
- real result artifacts listed by the replication log, resolved under
  `{{ codebase_dir }}` or `{{ replication_dir }}`

Actual ancestors: {{ ancestor_node_ids }}

Upstream node updates:

```json
{{ upstream_updates_json }}
```

Scope blockers on this lineage:

```json
{{ scope_blockers_json }}
```

Exact local/ancestor issues collected by orchestration:

```json
{{ lineage_issues_json }}
```

Inspect cited evidence rather than trusting labels. Never invent a result,
paper text, causal explanation, or evidence. If the claim is blocked, report it
as not assessable and identify the exact blocking paths. Include only issues
returned by the lineage collector; do not add a global risk list or unrelated
node issues.

Write this exact field structure (content may use paragraphs, tables, or lists):

```markdown
# Claim {{ claim_id }}

Paper result: ...

Reproduced result: ...

Upstream node results: ...

Direct comparison: ...

Scope blockers: ...

Lineage issues: ...

Assessment: close
```

`Upstream node results` must trace the D/P/T/M/V results actually supporting
the claim and cite their evidence paths. `Direct comparison` must compare the
paper and reproduced values/conditions directly, including absolute and
relative difference when meaningful. `Lineage issues` must preserve origin,
propagation path, and issue content.

Assessment must be exactly one of:

- `close`: all explicitly checkable conditions match within a paper tolerance,
  or, absent one, numeric relative error is at most 5%; structured results must
  match all reported components;
- `not close`: sufficient evidence exists and fails that criterion;
- `not assessable`: a required paper result, reproduced result, evidence, or
  lineage path is unavailable.

Use `not assessable` rather than inferring success from another claim. Reload
the fragment before finishing and confirm all seven field labels occur once and
all evidence paths are real.
