# Claim-driven validation weighting

Read the paper at `{{ paper_markdown }}` and graph at
`{{ paper_graph_path }}`. Work backward from paper C nodes and identify V nodes
that define strict prediction tasks with an executable baseline and a numeric
comparison target. Do not use reported performance values when selecting or
weighting V nodes.

Write `{{ weights_path }}`:

```json
{
  "validations": [
    {"validation_id": "V1", "weight": 1.0, "rationale": "central numeric task"},
    {"validation_id": "V2", "weight": 0.0, "rationale": "eligible but low importance"}
  ]
}
```

List every V you identify as eligible, in paper-graph order. Zero weight is the
normal way to sparsify low-importance eligible V nodes. At least one V must have
positive weight and all positive weights must sum to 1. A zero-weight V receives
no contract, execution, or score. Prefer V nodes whose result maps cleanly to a
numeric metric, but never select based on whether its baseline result looks
good or easy to improve.
