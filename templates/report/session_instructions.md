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

# Replication Report

**Status: Insufficient Specification**
**Mode:** {{ mode }}

{% if mode == "repo-only" %}
This repository was processed in repo-only mode (no paper provided).
The replication spec source was `{{ source_path }}` — but no verifiable
claims could be extracted from it.
{% elif mode == "paper-only" %}
This paper was processed in paper-only mode (no repository provided).
The replication spec source was `{{ source_path }}` — but no verifiable
claims could be extracted from it.
{% else %}
The replication spec source was `{{ source_path }}` — but no verifiable
claims could be extracted from it.
{% endif %}

A reproducible spec needs at least one numerical, structural, or
qualitative claim that can be verified by running the code. Suggested
remedies:

- Hand-author claims in JSON (`--claims path/to/claims.json`)
{% if not has_paper %}- Add a paper PDF (`--paper`) describing the project's claims
{% endif %}{% if mode == "repo-only" %}- Expand the README to describe expected outputs, metrics, or figures
{% endif %}

No score is reported.