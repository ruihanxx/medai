# Auto Research idea-assessment agent

Assess refinement `{{ idea_id }}` using frozen result-blind experiment weights.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Frozen result-blind experiment weights: `{{ weights_path }}`
- Implementation plan and audit: `{{ implementation_plan_path }}`, `{{ audit_path }}`
- Refinement experiment plan, log, and environment: `{{ experiment_plan_path }}`,
  `{{ experiment_log_path }}`, `{{ evidence_summary_path }}`
- Existing baseline log and environment: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`
- Base and refinement result roots: `{{ base_codebase_dir }}`,
  `{{ base_replication_dir }}`, `{{ codebase_dir }}`, `{{ experiment_dir }}`
- Passing threshold: `{{ assessment_threshold }}`

## Task

For every experiment, find the contract's frozen primary metric in the completed
replicate evidence and the refinement evidence. Copy only actual numeric values
and compute:

- `absolute_delta = refined_value - baseline_value`
- `relative_delta = absolute_delta / abs(baseline_value)`
- `score = relative_delta` for `higher`, otherwise `-relative_delta`
- `weighted_score = weight * score`

The total weighted score is the sum of all experiment weighted scores. If a
baseline value is zero, a value is missing, or evidence cannot be mapped, set
that experiment's unavailable derived fields and the total weighted score to
null; the verdict is `inconclusive`.

## Output

Write `{{ assessment_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "valid",
  "summary": "evidence-bound weighted conclusion",
  "audit_passed": true,
  "protocol_consistent": true,
  "experiments": [
    {
      "experiment_id": "E1",
      "metric_name": "frozen primary metric",
      "direction": "higher",
      "weight": 1.0,
      "baseline_value": 0.8,
      "refined_value": 0.82,
      "absolute_delta": 0.02,
      "relative_delta": 0.025,
      "score": 0.025,
      "weighted_score": 0.025,
      "evidence_paths": ["actual baseline and refinement result files"]
    }
  ],
  "weighted_score": 0.025,
  "threshold": {{ assessment_threshold }},
  "failure_reasons": []
}
```

## Constraints

- Include every weighted experiment exactly once and in order.
- `valid` requires a passing audit, a consistent protocol, a complete weighted
  score, and `weighted_score > threshold`.
- A complete score at or below the threshold is `invalid`.
- Preserve negative and inconclusive findings; do not infer missing values.
- Write only the requested assessment JSON.
