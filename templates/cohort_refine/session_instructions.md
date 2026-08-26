# Graph-node cohort refinement

Fix the failed scientific audit without changing the immutable paper graph.

Read:

- paper: `{{ paper_markdown }}`
- graph: `{{ paper_graph_path }}`
- scope: `{{ execution_scope_path }}`
- codegen plan: `{{ codegen_plan_path }}`
- audit: `{{ audit_report_path }}`
- codebase: `{{ codebase_dir }}`

Modify only code/configuration needed for audit issues routed to
`preprocessing_fix`. Preserve the meaning and IDs of graph nodes. Do not weaken
cohort rules, substitute sources, tune toward paper results, or change a shared
upstream implementation in a way that silently alters unrelated paths. Run
focused checks for each fix.

Update `codegen_plan.json["node_updates"]` with issue/resolution information on
the exact origin node. Preserve unrelated updates. Do not copy issues into
descendants and do not edit `graph/node_state.json`; orchestration assigns this
attempt's source and merges the update.

When remote execution is needed, follow
`{{ computation_provider_reference }}` and `{{ drive_reference }}`, reuse
`{{ remote_compute_state_path }}`, and keep raw remote data remote. Use the
plan's existing remote working/data directories.

Before finishing, reload the plan, verify all node IDs are runnable, ensure the
audit's required fixes are reflected in code and local update metadata, and
leave the codebase ready for the next independent audit attempt.
