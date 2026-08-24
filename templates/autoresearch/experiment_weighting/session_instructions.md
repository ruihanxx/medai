# Auto Research experiment-weighting agent

Assign result-blind scientific importance weights to the paper's experiments.

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Experiment definitions: `{{ experiments_path }}`

## Task

Read only the paper and experiment definitions. First select only experiments
that strictly train or evaluate a supervised model against an explicit
classification, regression, or risk/time-to-event prediction target. Exclude
direct statistical, association, explanatory, causal, matching, and effect-
estimation analyses that do not evaluate predictions, even when they are central
to the paper. If the paper mixes prediction and statistical analysis, continue
with only its strict prediction experiments. Before any refinement is
implemented or any baseline/refinement result is considered, assign each
selected experiment a positive importance weight based on how central it is to
the paper's prediction problem and proposed predictive method.

## Output

Write `{{ weights_path }}`:

```json
{
  "experiments": [
    {
      "experiment_id": "E1",
      "weight": 1.0,
      "rationale": "importance based only on the paper"
    }
  ]
}
```

## Constraints

- Include every selected strict prediction experiment exactly once and in input
  order; do not include excluded statistical experiments.
- Select at least one experiment; the preceding eligibility decision guarantees
  that the paper contains a strict prediction task.
- All weights must be positive and sum to exactly 1.
- Do not read or use result values, replication logs, reports, or generated code.
- Do not rank experiments by their reported performance.
- Write only the requested JSON artifact.
