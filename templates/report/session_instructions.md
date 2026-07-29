# Experiment report agent

Update the single report at `{{ report_path }}` for experiment
`{{ experiment_id }}`.

Read:
- Paper claims: `{{ claims_path }}`
- Paper Markdown and figures: `{{ paper_markdown }}`, `{{ paper_artifacts }}`
- Experiment definition: `{{ experiment_json }}`
- Replication result: `{{ result_path }}`

Create the report if absent. Preserve existing experiment sections. Add a
section comparing every claim's paper result with reproduced evidence and
recording every requested artifact and reproduced path. Do not invent missing
evidence.
