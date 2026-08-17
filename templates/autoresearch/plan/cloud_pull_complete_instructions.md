# Auto Research cloud materialization complete

Local orchestration completed cloud materialization. The read-only dataset is
recorded in `{{ computation_provider_state_path }}` and matches the inherited
base inventory. The instance is currently running and SSH-ready.

Continue the original experiment-planning instructions. Do not inspect raw
dataset content, rematerialize it, or copy it locally. Write the plan with the
exact state-owned working directory and completed dataset target in its
`remote_compute` object. Local orchestration will power the instance off after
validating the plan.
