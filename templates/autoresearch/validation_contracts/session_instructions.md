# Positive-weight V contract agent

## Delegation

For several distinct prediction paths, read
`{{ skills_dir }}/context-delegation/SKILL.md` and delegate read-only tracing of
baseline entry points, data/split definitions, and evaluator interfaces for
assigned positive-weight Vs. Group Vs sharing an evaluator or preprocessing
path. Workers receive only the relevant graph, weights, plans, and source code;
they must remain result-blind and must not open metric outputs, replication
results, reports, or transcripts, run the baseline, or edit source.

The parent reconciles shared frozen definitions, verifies exact source evidence
and editable paths, and writes the complete contracts in weight order. Handle a
single straightforward path directly; never include zero-weight Vs for delegation.

Read:

- graph: `{{ paper_graph_path }}`
- weights: `{{ weights_path }}`
- base codegen/replication plans: `{{ codegen_plan_path }}`,
  `{{ replicate_plan_path }}`
- base codebase: `{{ base_codebase_dir }}`

Write contracts only for positive-weight V nodes, in weight order. Zero-weight
V nodes must not appear. Trace each selected V to its actual baseline entry
point, editable refinement boundary, frozen inputs/targets/evaluator, primary
numeric metric, and exact comparison rule. Remain result-blind.

Write `{{ contracts_path }}`:

```json
{
  "validations": [
    {
      "validation_id": "V1",
      "baseline_entry_points": ["python baseline.py --validation V1"],
      "editable_paths": ["src/model.py", "src/train.py"],
      "frozen_contract": {
        "data": "fixed cohort/split",
        "target": "fixed outcome",
        "evaluator": "fixed complete V Cartesian block"
      },
      "primary_metric": "AUROC",
      "comparison_rule": {"direction": "higher", "tolerance": null}
    }
  ]
}
```

The contract is open: add any paper-specific fields required for auditability.
Do not invent enumerations. All editable paths must be repository-relative
existing files. Do not modify the base codebase.
