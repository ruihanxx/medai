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
- Base reproduction report with the audited paper-versus-replication context:
  `{{ base_reproduction_report }}`
- Base and refinement result roots: `{{ base_codebase_dir }}`,
  `{{ base_replication_dir }}`, `{{ codebase_dir }}`, `{{ experiment_dir }}`
- Passing threshold: `{{ assessment_threshold }}`

## Task

The assessment does not own experiment identity or configuration. Copy these
read-only fields without reinterpretation:

- `idea_id`: exactly the supplied idea ID.
- `experiment_id` and experiment order: exactly as frozen in the weights.
- `metric_name`: exactly, character for character, from the matching contract's
  `primary_metric`. Do not add a model, cohort, horizon, unit, display label,
  parenthetical qualifier, or any other prefix or suffix.
- `direction`: exactly from the matching contract's `metric_direction`.
- `weight`: exactly from the matching frozen experiment weight.
- `threshold`: exactly the supplied passing threshold.
- `audit_passed`: exactly the verdict represented by the supplied audit.

Treat exact equality, not containment or semantic equivalence, as the check for
every copied string. Do not edit the frozen contracts or weights. The assessment
agent owns only evidence mapping, numeric comparisons, protocol-consistency
judgment, scores and rationales, the summary, verdict, and failure reasons.

For every experiment, find the contract's frozen primary metric in the completed
replicate evidence and the refinement evidence. Copy only actual numeric values
and compute:

- `absolute_delta = refined_value - baseline_value`
- `relative_delta = absolute_delta / abs(baseline_value)`
- assign an integer `score` from -5 through 5 using the rubric below
- `weighted_score = weight * score`

The score is an evidence-bound scientific judgment, not another expression of
the relative delta. Judge whether the idea works from the actual completed
replicate and refinement results, using the frozen metric direction, evaluation
protocol, uncertainty, consistency across runs/folds/cohorts when available,
and the scale of improvement that was meaningful in the original study. Use the
base reproduction report only to calibrate that historical effect scale; never
copy a paper-reported value into the refinement result or treat it as a target.

For example, if the audited report shows that the original paper's method moved
the relevant performance from approximately 0.75 to 0.78, an actual refinement
move from 0.78 to 0.80 under the same frozen protocol may justify a very strong
score even though its relative delta is numerically small. Explain the judgment
for every experiment in `score_rationale`.

Use this integer rubric:

- `-5`: compelling evidence that the idea materially worsens the experiment.
- `-4` or `-3`: clear or substantial worsening.
- `-2` or `-1`: small, uncertain, or limited worsening.
- `0`: no meaningful improvement; unchanged, negligible, or mixed evidence
  provides no net reason to believe the idea works.
- `1` or `2`: limited or modest evidence of improvement.
- `3` or `4`: clear or strong evidence that the idea improves the experiment.
- `5`: compelling evidence, in the scientific context of the replicated study,
  that the idea works well.

The total weighted score is the sum of all experiment weighted scores. Do not
renormalize weights. If a baseline value is zero, a value is missing, or
evidence cannot be mapped, set that experiment's unavailable derived fields,
`score`, `weighted_score`, and the total weighted score to null; the verdict is
`inconclusive`. Still provide a non-empty `score_rationale` that identifies the
missing, zero-baseline, or unmappable evidence that prevented scoring.

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
      "metric_name": "<copy primary_metric exactly>",
      "direction": "higher",
      "weight": 1.0,
      "baseline_value": 0.8,
      "refined_value": 0.82,
      "absolute_delta": 0.02,
      "relative_delta": 0.025,
      "score": 5,
      "score_rationale": "The observed improvement is strong relative to the original study's meaningful effect scale and is consistent under the frozen evaluation protocol.",
      "weighted_score": 5.0,
      "evidence_paths": ["actual baseline and refinement result files"]
    }
  ],
  "weighted_score": 5.0,
  "threshold": {{ assessment_threshold }},
  "failure_reasons": []
}
```

## Constraints

- Include every weighted experiment exactly once and in order.
- Never rename, decorate, normalize, or otherwise change a frozen metric name,
  direction, weight, experiment ID, or threshold in the assessment.
- `valid` requires a passing audit, a consistent protocol, a complete weighted
  score, and `weighted_score > threshold`.
- A complete score at or below the threshold is `invalid`.
- Every score must be an integer from -5 through 5 and must have a specific,
  evidence-bound `score_rationale`. Do not derive it mechanically from
  `relative_delta` or use a fixed percentage-to-score conversion.
- A non-valid verdict must list concrete `failure_reasons`; a valid verdict must
  use an empty list.
- Preserve negative and inconclusive findings; do not infer missing values.
- Write only the requested assessment JSON.
