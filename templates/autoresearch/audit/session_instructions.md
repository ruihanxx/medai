# Refinement validation audit

Audit idea `{{ idea_id }}` without editing code or graph.

## Delegation

For a large refinement, read `{{ skills_dir }}/context-delegation/SKILL.md` and
delegate read-only evidence checks for coherent contracted-V paths or shared
scientific changes. Supply the exact contracts, base/refined source and graph
versions, and declared editable files. Readers return freely named checks with
source evidence and concrete failures; they neither fix code nor execute the
baseline or validation experiments.

The parent verifies global base-node immutability, allowed deltas, shared
dependencies, new-node representation, and coverage of every positive V and its
complete Cartesian block. Merge duplicate diagnoses without losing per-V
evidence, then derive the single overall verdict and required fixes. A compact
change can be audited directly.

Read contracts, base/refined graphs, implementation plan, and both codebases:

- `{{ contracts_path }}`
- `{{ base_graph_path }}` and `{{ refinement_graph_path }}`
- `{{ implementation_plan_path }}`
- `{{ base_codebase_dir }}` and `{{ codebase_dir }}`

Use freely named checks appropriate to the refinement. For every positive-weight
baseline V, include at least one evidence-backed check of its corresponding new
V. Verify base nodes are byte-for-byte semantically unchanged, changed P/T/M
semantics are represented by new nodes, any model/parameter change creates a
new M, baseline mapping is explicit, frozen contracts remain unchanged, only
declared/editable code changed, and the refined V executes its complete
Cartesian block without rerunning the baseline.

Write `{{ audit_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "pass",
  "refinement_only": true,
  "scope_evidence": ["specific graph/code evidence"],
  "scope_issue": null,
  "checks": [
    {
      "validation_id": "V1",
      "name": "free-form frozen evaluator check",
      "verdict": "pass",
      "evidence": ["path:line or artifact"],
      "issue": null
    }
  ],
  "required_fixes": []
}
```

Check names are free-form; do not use a fixed aspect taxonomy. A failed check
needs an issue. Overall pass requires refinement_only=true, no scope issue, all
checks pass, and no required fixes. Overall fail requires concrete fixes.
