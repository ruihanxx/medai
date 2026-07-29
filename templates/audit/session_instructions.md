# Codegen audit agent

Audit and modify the writable codebase at `{{ codebase_dir }}`.

Inputs:
- Claims: `{{ claims_path }}`
- Experiments: `{{ experiments_path }}`
- Resources: `{{ resources_path }}`
- Skills: `{{ skills_dir }}`
- AutoDL state, when remote compute was selected: `{{ autodl_state_path }}`

Required work:

1. Ensure code outputs cover every experiment claim and artifact; modify code if needed.
2. Install all dependencies.
3. Check full-scale memory, chunking, batches, and compute use against available resources.
4. Run smoke tests and debug failures.
5. Write `{{ replicate_plan_path }}`:

```json
{"experiments":[{"experiment_id":"E1","claims":["C1"],"artifacts":["Figure 1"],"steps":[{"step_id":"S1","description":"...","command":"...","expected_outputs":["path"]}]}]}
```

The mappings must exactly match `experiment_todo.json`.

Hard constraints: do not change model semantics, provide a fallback plan, reduce
the prescribed experiment scale, or hardcode experimental results.
