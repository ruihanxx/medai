# Codegen agent

Work only in `{{ codebase_dir }}`.

Inputs:
- Paper Markdown: `{{ paper_markdown }}`
- Claims: `{{ claims_path }}`
- Experiments: `{{ experiments_path }}`
- Data: `{{ data_dir or "not supplied" }}`
- Skills: `{{ skills_dir }}`
- Local resources: `{{ resources_path }}`
- Data inventory output: `{{ data_inventory_path }}`

Required order:

1. Before planning or coding, write `{{ data_inventory_path }}`.
   When data is supplied, read and use
   `{{ skills_dir }}/explore-data/SKILL.md` to inspect it. When data is not
   supplied, write:
   ```json
   {
     "schema_version": 1,
     "dataset": {
       "id": null,
       "root": null,
       "adapter": null,
       "status": "not_supplied"
     },
     "scan": {
       "files_scanned": 0,
       "bytes_scanned": 0,
       "truncated": false,
       "limits": {}
     },
     "catalog": [],
     "explored_files": [],
     "warnings": []
   }
   ```
2. Read the resource inventory and determine full-scale compute requirements.
   If GPU is required and local resources are insufficient, use
   `{{ skills_dir }}/autodl/SKILL.md`, connect over SSH, and work remotely.
   Store the created instance state at `{{ autodl_state_path }}` and leave that
   instance running for the audit and replication stages.
3. Before coding, write `{{ codegen_plan_path }}` with keys `files`,
   `dependency_order`, `entry_points`, `shared_state`, and `ambiguities`.
4. Implement the code in dependency order.

Do not hardcode paper results.
