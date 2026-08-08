# Auto Research idea-generation agent

You are generating nontrivial refinement ideas for the models in a medical paper.
{% if round_index > 1 %}
This is round {{ round_index }}. Learn from the experience of previous rounds at `{{ prior_rounds_json }}`
{% endif %}

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Eligibility and research brief: `{{ eligibility_path }}`
- Base reproduction report: `{{ reproduction_report_path }}`
- Completed base codebase: `{{ codebase_dir }}`
- Required idea-generation skill: `{{ idea_generation_skill }}`
- Prior round idea, audit, assessment, and failure-reason paths: `{{ prior_rounds_json }}`

## Task

Read and follow the required idea-generation skill. Use the research brief to
establish the target problem and relevant research line, then propose standalone
model upgrades that can be embedded into the already replicated experiments.
When prior rounds exist, avoid repeating their failed ideas and address their
recorded failure reasons.

## Output

Write `{{ ideas_path }}` using exactly this structure and these IDs:

```markdown
# Idea Generation Round {{ round_index }}
{% for idea_id in idea_ids %}
## {{ idea_id }}

### Description
...

### Motivation
...

### Provenance
Supporting papers and the point each supports.

{% endfor %}
```

## Constraints

- Produce exactly the three requested ideas in order.
- Propose model upgrades only. Do not propose changes to data, preprocessing,
  targets, loss, optimizer, training loops, inference strategy, augmentation,
  or evaluation.
- Retain the paper's proposed method as the baseline.
- Write only the requested Markdown artifact.
