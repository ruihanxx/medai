# Auto Research experiment-weighting agent

Assign result-blind scientific importance weights to the paper's experiments.

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Experiment definitions: `{{ experiments_path }}`

## Task

Read only the paper and experiment definitions. Before any refinement is
implemented or any baseline/refinement result is considered, assign each
experiment a positive importance weight based on how central it is to the
paper's stated problem and proposed method.

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

- Include every experiment exactly once and in input order.
- All weights must be positive and sum to exactly 1.
- Do not read or use result values, replication logs, reports, or generated code.
- Do not rank experiments by their reported performance.
- Write only the requested JSON artifact.
