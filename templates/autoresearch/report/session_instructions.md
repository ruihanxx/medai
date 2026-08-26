# Auto Research report agent

Write `{{ report_path }}` from the immutable base report, validation setup, and
canonical round/idea artifacts.

Read:

- eligibility: `{{ eligibility_path }}`
- validation weights/contracts: `{{ weights_path }}`, `{{ contracts_path }}`
- base claim report: `{{ base_reproduction_report }}`
- round artifacts:

```json
{{ rounds_json }}
```

Use exactly:

```markdown
# Auto Research Report

## 1. Base problem and research context
## 2. Idea ledger
## 3. Validation comparisons
## 4. Validity and failure assessment
## 5. Visualizations
```

Include every attempted idea and every positive-weight baseline/refined V
comparison, with V IDs, related paper claims, frozen metric/rule/weight, actual
values, deltas, score, weighted contribution, evidence, and verdict. State that
zero-weight V nodes were intentionally not contracted, executed, or scored.
Describe audit failures and inconclusive numeric mappings precisely. Use only
V IDs and claim IDs; do not invent missing results.

Embed `{{ metric_visualization_path }}` and
`{{ status_visualization_path }}` by filename in section 5. Ensure every idea ID
appears and the section order is exact.
