# Preprocessing agent

Read `{{ paper_markdown }}` and its images under `{{ artifacts_dir }}`.

1. Write every verifiable text or numeric result claim to `{{ claims_path }}`:

```json
{"claims":[{"claim_id":"C1","statement":"...","kind":"text|numeric","paper_result":"...","provenance":{"page":1,"section":"..."}}]}
```

Do not create figure or table claims.

2. Write `{{ experiments_path }}`:

```json
{"experiments":[{"experiment_id":"E1","description":"...","claims":["C1"],"artifacts":["Table 3","Figure 4"]}]}
```

One experiment includes training one model group and all downstream evaluation
and comparison. Do not split evaluation from its training experiment. Every
claim must belong to at least one experiment.
