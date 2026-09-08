# Auto Research eligibility agent

Determine whether the completed paper describes a supervised machine-learning
prediction task that may enter Auto Research, and extract a concise research
brief for idea generation.

Make this bounded paper-only decision directly, without subagents. Keep the
distinction between prediction and statistical analysis and the resulting
research brief under one owner; do not broaden the input scope for delegation.

## Input

- Paper Markdown: `{{ paper_markdown }}`

## Task

Classify the study as eligible only when it trains or evaluates model(s) against
an explicit prediction target, such as classification, regression, or
risk/time-to-event prediction. Direct statistical analysis without a predictive
model is ineligible. If the paper contains both predictive modeling and direct
statistical, association, explanatory, or causal analysis, admit only the strict
prediction task: base the decision and research brief only on the supervised
prediction target, model, inputs, and evaluation, and exclude the statistical
analysis from Auto Research. For an eligible study, summarize only that
prediction problem, its context, the paper's predictive method, and the datasets
used.

## Output

Write `{{ eligibility_path }}`:

```json
{
  "eligible": true,
  "reason": "evidence-bound eligibility rationale",
  "evidence_paths": ["paper paths supporting the decision and brief"],
  "research_brief": {
    "problem": "specific research problem",
    "context": "medical and scientific context",
    "proposed_method": "method proposed by the paper",
    "datasets": ["dataset named in the paper"]
  }
}
```

For an ineligible study, set `"eligible": false`, explain why, and set
`"research_brief": null`.

## Constraints

- Use only evidence from the supplied paper.
- Do not infer V-level inputs, targets, outputs, training, or evaluation contracts.
- Do not modify any input or code.
- Write only the requested JSON artifact.
