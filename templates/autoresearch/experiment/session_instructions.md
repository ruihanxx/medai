# Auto Research experiment agent

Execute the planned refinement experiments for `{{ idea_id }}`.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Experiment plan: `{{ experiment_plan_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Writable idea codebase: `{{ codebase_dir }}`
- Data: `{{ data_dir or "not supplied" }}`
- Existing baseline log and environment: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`
- Remote-compute state: `{{ computation_provider_state_path }}`

## Task

Execute every experiment and its steps in order. Run only the audited refinement
through its declared experiment entry point. Never rerun or alter the replicated
baseline. Preserve actual outputs. If execution fails, record the failure
without editing the already audited code.

## Output

After every completed step, rewrite `{{ experiment_log_path }}`:

```json
{
  "experiments": [
    {
      "experiment_id": "E1",
      "step_outcomes": [
        {
          "step_id": 1,
          "description": "step description",
          "command_executed": "actual refinement-only command",
          "exit_code": 0,
          "stdout": "captured output",
          "stderr": "captured error output",
          "output_files": ["actual output paths"],
          "duration_seconds": 1.0,
          "fixes_applied": [],
          "code_modified": false,
          "notes": "observations"
        }
      ]
    }
  ]
}
```

Write `{{ evidence_summary_path }}` using the existing evidence-summary schema.

## Constraints

- Store experiment artifacts inside `{{ codebase_dir }}` or `{{ experiment_dir }}`.
- Never execute a baseline entry point or overwrite base results.
- Never fabricate, hard-code, or overwrite computed refinement results.
- Do not modify any code; every `code_modified` value must be false and every
  `fixes_applied` list must be empty.
- Do not modify the base run or source data.
