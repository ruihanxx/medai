# Auto Research experiment agent

Execute the planned refinement experiment for `{{ idea_id }}` and debug it when
necessary.

## Inputs

- Experiment plan: `{{ experiment_plan_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Writable idea codebase: `{{ codebase_dir }}`
- Data: `{{ data_dir or "not supplied" }}`
- Existing baseline log and environment: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`
- Remote-compute state: `{{ computation_provider_state_path }}`

## Task

Execute every plan step in order. Run only the refinement; do not rerun or alter
the baseline. Debug execution failures as needed and preserve actual outputs.

## Output

After every completed step, rewrite `{{ experiment_log_path }}`:

```json
{
  "step_outcomes": [
    {
      "step_id": 1,
      "description": "step description",
      "command_executed": "actual command",
      "exit_code": 0,
      "stdout": "captured output",
      "stderr": "captured error output",
      "output_files": ["actual output paths"],
      "duration_seconds": 1.0,
      "fixes_applied": [
        {"file_path": "path", "description": "fix", "original_error": "error", "diff_snippet": "before/after"}
      ],
      "code_modified": false,
      "notes": "observations"
    }
  ]
}
```

Write `{{ evidence_summary_path }}`:

```json
{
  "environment": {
    "python_version": "version",
    "gpu_available": false,
    "gpu_model": null,
    "key_packages": {"package": "version"}
  }
}
```

## Constraints

- Store experiment artifacts inside `{{ codebase_dir }}` or `{{ experiment_dir }}`.
- Never fabricate, hard-code, or overwrite computed results.
- Do not modify the base run or source data.
