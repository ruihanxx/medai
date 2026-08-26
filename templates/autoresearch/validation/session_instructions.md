# Refined-V executor

Execute the refinement-only plan for `{{ idea_id }}`.

Read:

- contracts: `{{ contracts_path }}`
- plan: `{{ validation_plan_path }}`
- graph/overlay: `{{ refinement_graph_path }}`, `{{ node_state_path }}`
- implementation/audit: `{{ implementation_plan_path }}`, `{{ audit_path }}`
- base run evidence: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`

Execute every refined V entry and step in order. Run only new refinement paths;
do not invoke baseline entry points, modify audited source, change frozen
contracts, or execute zero-weight V nodes. Preserve full intended scale and the
complete refined-V Cartesian product.

Write `{{ validation_log_path }}` incrementally:

```json
{
  "validations": [
    {
      "validation_id": "V_refined_1",
      "step_outcomes": [
        {
          "step_id": 1,
          "description": "what ran",
          "command_executed": "actual command",
          "exit_code": 0,
          "stdout": "bounded output",
          "stderr": "",
          "output_files": ["real/refined_metric.json"],
          "duration_seconds": 1,
          "fixes_applied": [],
          "code_modified": false,
          "notes": "observations"
        }
      ]
    }
  ],
  "node_updates": [
    {
      "node_id": "M_refined_1",
      "result": {"artifact": "real/model.bin"},
      "evidence": ["real/model.bin"],
      "issues": []
    },
    {
      "node_id": "V_refined_1",
      "result": {"primary_metric": 0.82},
      "evidence": ["real/refined_metric.json"],
      "issues": []
    }
  ]
}
```

Node updates must cover every node added by the refinement graph exactly once,
with nonempty actual result and existing evidence. Keep issues local. The
orchestrator merges them into the idea overlay after validation.

Write `{{ evidence_summary_path }}` using the standard environment schema.
All outputs must exist under `{{ codebase_dir }}` or `{{ validation_dir }}`.

{% if command_handoff %}
Use the requested structured command handoff. Maintain the run-owned environment
under `{{ local_environment_dir }}` and artifacts under
`{{ local_artifact_dir }}`. Return one command/download operation at a time;
orchestration executes it and resumes this session. Keep raw cloud data remote.
{% endif %}
