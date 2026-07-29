# Replicate agent

Execute the complete plan at `{{ replicate_plan_path }}` in
`{{ codebase_dir }}`. Do not reduce scale or invent fallback runs.
If the plan uses remote compute, use the AutoDL skill at `{{ skills_dir }}/autodl`
and the existing instance state at `{{ autodl_state_path }}`.

For every experiment write:

`{{ replication_dir }}/<experiment_id>/result.json`

```json
{"experiment_id":"E1","claims":[{"claim_id":"C1","reproduced_result":"...","evidence":["path"]}],"artifacts":[{"artifact_id":"Figure 1","path":"path"}],"commands":["actual command"]}
```

The required experiment mappings, without paper target values, are:

{{ experiment_mappings }}

Record only results and artifacts actually produced by executed commands.
