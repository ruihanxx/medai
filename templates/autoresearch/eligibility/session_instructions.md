# Auto Research eligibility agent

Determine whether the completed base run is a supervised machine-learning
prediction task that may enter Auto Research.

## Inputs

- Base manifest: `{{ base_manifest }}`
- Paper Markdown: `{{ paper_markdown }}`
- Claims: `{{ claims_path }}`
- Experiments: `{{ experiments_path }}`
- Codegen plan and codebase: `{{ codegen_plan_path }}`, `{{ codebase_dir }}`
- Replication plan, log, and environment: `{{ replicate_plan_path }}`,
  `{{ replication_log_path }}`, `{{ evidence_summary_path }}`
- Reproduction report: `{{ reproduction_report_path }}`

## Task

Classify the study as eligible only when it trains or evaluates a model against
an explicit prediction target, such as classification, regression, or risk/time-to-event
prediction. Direct statistical analysis without a predictive model is ineligible.
For an eligible run, extract the fixed research anchors from the base evidence.

## Output

Write `{{ eligibility_path }}`:

```json
{
  "eligible": true,
  "reason": "evidence-bound eligibility rationale",
  "evidence_paths": ["paths supporting the decision"],
  "anchors": {
    "task": "research task",
    "prediction_target": "fixed target",
    "dataset": "fixed dataset",
    "cohort": "fixed cohort",
    "inputs": ["fixed model inputs"],
    "outputs": ["fixed model outputs"],
    "metrics": ["fixed evaluation metrics"],
    "experiment_protocol": ["fixed split and evaluation protocol"],
    "baseline_method": "original paper method"
  }
}
```

For an ineligible study, set `"eligible": false`, explain why, and set
`"anchors": null`.

## Constraints

- Use only evidence from the supplied base run.
- Do not modify the base run or any code.
- Write only the requested JSON artifact.
