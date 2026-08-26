# Refinement graph codegen agent

Implement idea `{{ idea_id }}` inside `{{ codebase_dir }}` without modifying
the base run.

Read the idea, eligibility decision, positive-weight contracts, base graph,
base plans, and base code:

- `{{ ideas_path }}`
- `{{ eligibility_path }}`
- `{{ contracts_path }}`
- `{{ paper_graph_path }}`
- `{{ base_codegen_plan_path }}` and `{{ base_replicate_plan_path }}`
- `{{ base_codebase_dir }}`
{% if repair_audit_path %}- repair audit: `{{ repair_audit_path }}`{% endif %}

Change only files within contract `editable_paths` or new declared files. Keep
data, target, evaluator, primary metric, and comparison rule frozen. Implement
only refinement paths for positive-weight V nodes; do not rerun or alter
baselines in this stage.

Write `{{ implementation_plan_path }}` with open method details:

```json
{
  "idea_id": "{{ idea_id }}",
  "summary": "refinement summary",
  "method": {"paper-specific": "implementation semantics"},
  "refine_file_list": [{"file_path": "src/model.py", "change": "exact change"}],
  "new_file_list": [{"file_path": "src/refined_model.py", "change": "new artifact"}]
}
```

Also write a complete merged PaperGraph to `{{ refinement_graph_path }}`. Copy
every base node unchanged with the same ID, then add every changed P/T/M and one
new V for each positive-weight baseline V. Every new V must add
`baseline_validation_id` with the corresponding baseline ID. Add narrowly
scoped refined C nodes (with `baseline_claim_id`) when needed so every new path
reaches a claim without modifying a base C in place. Any model,
parameter, seed, training-input, fine-tuning, or architecture change creates a
new M; never modify a base M or any other base node in place. New refined C
nodes are transformation endpoints, not new assertions attributed to the
paper. The resulting full graph must pass the same uniqueness,
reference, acyclicity, and claim reachability checks as the base graph.

Prefer fine-grained new nodes over overloaded nodes. Expand the refined V's
complete model/data/metric Cartesian product. Run only lightweight syntax and
interface checks here, not full validation. Do not edit the idea node-state
overlay; orchestration creates it after graph validation.
