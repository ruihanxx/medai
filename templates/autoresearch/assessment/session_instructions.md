# Auto Research idea-assessment agent

Assess whether refinement `{{ idea_id }}` produced a valid improvement.

## Inputs

- Round ideas: `{{ ideas_path }}`
- Eligibility and fixed anchors: `{{ eligibility_path }}`
- Implementation plan and audit: `{{ implementation_plan_path }}`, `{{ audit_path }}`
- Experiment plan, log, and environment: `{{ experiment_plan_path }}`,
  `{{ experiment_log_path }}`, `{{ evidence_summary_path }}`
- Base replication log, environment, and report: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`, `{{ base_reproduction_report }}`
- Base result roots: `{{ base_codebase_dir }}`, `{{ base_replication_dir }}`

## Task

Compare actual base evidence with actual refinement evidence under the fixed
protocol. A supported improvement must follow the metric direction. When
uncertainty is available it must exceed the recorded noise threshold; otherwise
any strictly positive direction-adjusted delta is sufficient. Missing or
unmappable evidence is inconclusive.

## Output

Write `{{ assessment_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "valid, invalid, or inconclusive",
  "summary": "evidence-bound conclusion",
  "audit_passed": true,
  "protocol_consistent": true,
  "primary_metric": {
    "name": "metric",
    "direction": "higher or lower",
    "baseline_value": 0.0,
    "refined_value": 0.0,
    "absolute_delta": 0.0,
    "relative_delta": null,
    "uncertainty_available": false,
    "noise_threshold": null,
    "uncertainty_method": null,
    "improvement_supported": false
  },
  "secondary_metrics": [],
  "evidence_paths": ["paths used"],
  "failure_reasons": ["why not valid"]
}
```

`absolute_delta` is refined minus baseline. `relative_delta` is that delta
divided by the absolute baseline, or null when the baseline is zero. Set
`primary_metric` to null when no comparable primary metric exists.

## Constraints

- `valid` requires a passing audit, a consistent protocol, and supported primary improvement.
- Preserve negative and inconclusive findings; do not infer missing values.
- Write only the requested assessment JSON.
