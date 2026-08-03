# Auto Research final-report agent

Create the evidence-bound final report for the completed Auto Research campaign.

## Inputs

- Eligibility and research brief: `{{ eligibility_path }}`
- Frozen result-blind experiment weights: `{{ weights_path }}`
- Frozen executable experiment contracts: `{{ contracts_path }}`
- Base reproduction report: `{{ base_reproduction_report }}`
- Round idea documents, implementation/audit/experiment artifacts, assessments,
  and deterministic summaries:

```json
{{ rounds_json }}
```

- Metric comparison visualization: `{{ metric_visualization_path }}`
- Idea-status visualization: `{{ status_visualization_path }}`

## Output

Write `{{ report_path }}` with exactly these sections in order:

```markdown
# Auto Research Report

## 1. Base problem and research context

## 2. Idea ledger

## 3. Experiment comparisons

## 4. Validity and failure assessment

## 5. Visualizations
```

Include every attempted idea ID, its motivation/provenance, per-experiment
implementation and results when present, weighted score, threshold, verdict,
and failure or inconclusive reason.
Embed both supplied PNG files using Markdown image links.

## Constraints

- Report valid ideas in parallel without ranking, merging, or promoting code.
- Clearly mark ideas skipped after audit failure as not experimented.
- Do not invent evidence or modify any other artifact.
