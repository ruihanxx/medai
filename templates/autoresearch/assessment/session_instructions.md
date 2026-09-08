# Numeric validation assessment

Assess refinement `{{ idea_id }}` from real evidence.

## Delegation

Perform ordinary numeric mapping, arithmetic, and scoring directly. Only when
many distinct artifacts require substantial inspection, read
`{{ skills_dir }}/context-delegation/SKILL.md` and delegate read-only extraction
of exact baseline/refined value pairs for assigned positive Vs. Include frozen
metric definitions and endpoint identities; require source paths/keys, units,
conditions, and explicit missing or incomparable values. Workers must not run
experiments, substitute metrics, choose favorable endpoints, or set scores.

The parent verifies mappings and protocol/audit status, copies all frozen
rules/weights, computes deltas and contributions, and assigns the overall
verdict. Preserve inconclusive evidence rather than filling gaps from summaries.

Read contracts/weights, refined plan/log, audit, base/refined node states, and
the cited output artifacts:

- `{{ contracts_path }}`, `{{ weights_path }}`
- `{{ validation_plan_path }}`, `{{ validation_log_path }}`
- `{{ audit_path }}`
- `{{ base_node_state }}`, `{{ refinement_node_state }}`
- `{{ base_replication_log }}`, `{{ evidence_summary_path }}`

For each positive-weight baseline V, extract the frozen primary metric's numeric
baseline value and the corresponding refined V value. Copy the exact primary
metric, comparison rule, and weight from the frozen artifacts. Compute
`absolute_delta = refined - baseline` and
`relative_delta = absolute_delta / abs(baseline)` when baseline is nonzero.
Apply the frozen comparison rule and give an evidence-bound scientific score
from -5 to 5. `weighted_score = score * weight`; total weighted score is the
sum. Do not execute, impute, or score zero-weight V nodes.

Write `{{ assessment_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "valid",
  "summary": "evidence-bound summary",
  "audit_passed": true,
  "protocol_consistent": true,
  "validations": [
    {
      "validation_id": "V1",
      "refined_validation_id": "V_refined_1",
      "primary_metric": "AUROC",
      "comparison_rule": {"direction": "higher"},
      "weight": 1.0,
      "baseline_value": 0.8,
      "refined_value": 0.82,
      "absolute_delta": 0.02,
      "relative_delta": 0.025,
      "score": 2,
      "score_rationale": "scientific magnitude and uncertainty rationale",
      "weighted_score": 2.0,
      "evidence_paths": ["base metric artifact", "refined metric artifact"]
    }
  ],
  "weighted_score": 2.0,
  "threshold": {{ assessment_threshold }},
  "failure_reasons": []
}
```

Use `inconclusive` with null derived scores when actual numeric values cannot be
mapped. Failed audit or protocol inconsistency requires `invalid`. Otherwise a
total strictly greater than the configured threshold is valid; equal or lower
is invalid. Cite only existing base-run or idea files.
