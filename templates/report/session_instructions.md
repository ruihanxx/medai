# Claim report agent

Write one evidence-bound Markdown fragment for claim `{{ claim_id }}` to
`{{ claim_report_path }}`. This is an evidence audit, not a narrative summary.
Do not edit another claim fragment or the combined report. A later final-report
agent indexes the validated fragments without changing their conclusions.

## Inputs

- Current claim node:

```json
{{ claim_json }}
```

- Paper Markdown and figures/tables: `{{ paper_markdown }}`, `{{ paper_artifacts }}`
- Immutable paper graph and node overlay: `{{ paper_graph_path }}`, `{{ node_state_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Replication plan: `{{ replicate_plan_path }}`
- Replication step log: `{{ replication_log_path }}`
- Replication environment summary: `{{ evidence_summary_path }}`
- Replication output files: paths listed in `replication_log.json["step_outcomes"]`;
  resolve relative paths against `{{ codebase_dir }}` and then `{{ replication_dir }}`
- Claim-specific Smart Replicate log when present:
  `{{ replication_dir }}/claims/{{ claim_id }}/smart_replicate_log.json`

Actual claim and ancestor node IDs:

```json
{{ ancestor_node_ids }}
```

Upstream node updates supplied for only this lineage:

```json
{{ upstream_updates_json }}
```

Scope blockers supplied for only this lineage:

```json
{{ scope_blockers_json }}
```

Exact local/ancestor issues collected by orchestration:

```json
{{ lineage_issues_json }}
```

## Evidence audit

Inspect cited evidence and the underlying output files rather than trusting labels or copying summaries. Never invent paper text, values, artifact content, experimental outputs, causal explanations, or evidence. Preserve discrepancies instead of explaining them away.

### Paper result and provenance

Use the current C node only. Report its `paper_result` exactly; if absent, write `not reported`. Include its statement/role/kind when present and identify every source-exact provenance quote, page, section, and Figure/Table label relevant to the result. Preserve the quote verbatim rather than replacing it with a paraphrase.

When the claim or provenance references a Figure/Table, locate the original caption, table text, and source path through the paper Markdown and `{{ paper_artifacts }}`. Inspect the original asset when interpretation requires it. Do not infer a paper value from pixels when the text/table does not state it.

### Reproduced result and artifacts

Derive the reproduced result from the current C node's actual `replicate_agent` update, its supporting V results, the execution log, and real output files. If the required result or evidence is absent, write `not produced`; never infer it from another claim or from the paper.

For every Figure/Table artifact required by this claim, identify the reproduced artifact path and make a content-level comparison with the paper original: relevant labels, conditions, axes/units, cohorts, components, or table entries. A pair of paths alone is not a comparison. If an original or reproduced artifact cannot be found, say so explicitly.

If a claim-specific Smart Replicate log exists, distinguish the preserved baseline from later hypothesis-driven rounds, report the final result actually represented in node updates, and retain unresolved divergence. Do not present anchor-guided changes as part of the independent baseline.

### Upstream result trace

Trace every D/P/T/M/V node that actually supports this C, following graph inputs rather than prose relevance. For each node, state its actual result or artifact description and cite its real evidence path. Confirm that each consumer used the declared predecessor artifact. Do not include unrelated available nodes or infer one path's success from another.

If the claim is blocked, do not search for or infer execution evidence. Mark the claim `not assessable`, identify each exact blocking origin and dependency path, and use `not produced` for unavailable reproduced outputs. The combined report will identify the run as partial from the scope; do not hide partial coverage.

### Direct comparison

Compare the paper and reproduced result directly:

- For a numeric result, show the absolute difference and relative error. If the paper value is zero or relative error is not meaningful, state the domain-appropriate comparison used.
- For a structured numeric result, assess every reported component; do not cherry-pick the closest component.
- For a qualitative, structural, or artifact-backed result, enumerate every explicitly checkable matched and unmatched condition.
- Apply the paper's stated tolerance when one exists. Otherwise use the assessment criteria below.

### Lineage risk audit

Use only objects supplied in `lineage_issues_json`. Preserve each issue's origin node, source, propagation path, and content; do not merge distinct issues or copy them onto descendants. For each issue, explain only the evidence-supported mechanism by which it can affect this claim, identify affected lineage nodes/artifacts, assign severity `low`, `medium`, or `high` with a brief evidence-bound reason, and state what evidence would resolve or reduce the risk. Do not add a global risk list, unrelated node issues, or generic risks.

## Output

Write this exact field structure. Content under a label may use paragraphs, tables, or lists, but every label must occur exactly once:

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

Assessment must be exactly one of:

- `close`: all explicitly checkable conditions are reproduced within the paper's stated tolerance; when no tolerance is stated, a numeric result has relative error at most 5%, or a text/structural result matches every explicitly checkable key condition;
- `not close`: sufficient evidence exists but fails that criterion;
- `not assessable`: the paper result, reproduced result, required evidence, artifact, or lineage path is unavailable. Missing evidence is never `close`.

Judge this claim independently. Before finishing, reload the fragment and verify the heading contains the exact current claim ID; all seven field labels occur once; every paper quote is source-exact; every required component and artifact has been assessed; every scope blocker and supplied lineage issue is covered; no unrelated issue appears; every evidence path is real; and exactly one valid assessment is present.
