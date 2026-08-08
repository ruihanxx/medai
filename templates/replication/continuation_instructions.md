# Replication continuation agent

The previous agent invocation returned before the current replication attempt
completed. This is a continuation of that same attempt, not a new attempt.

Read the original replication instructions at `{{ initial_prompt_path }}` and
the plan at `{{ replicate_plan_path }}`. Every scientific, evidence, remote
lifecycle, and output-attribution contract in those instructions remains in
force. The instruction to restart at plan step 1 is the only exception.

The current valid logged prefix is `{{ completed_step_ids }}` in
`{{ replication_log_path }}`. Continue from plan step
`{{ first_missing_step_id }}`. Do not rerun a logged step or treat old outputs
as evidence for an unlogged step.

Before starting the first missing step, inspect whether its command is already
running. If it is, wait for that exact command instead of launching a duplicate.
If it terminated without completing the step, diagnose the available evidence
and rerun only that incomplete step when necessary.

Keep each long-running command attached to one execution handle and wait on or
poll that same handle until it reaches a terminal status. Do not create
standalone `sleep` commands as timers, launch overlapping progress probes, or
return while a plan command or tool call remains in progress. Keep progress
checks sparse and bounded.

Work from `{{ codebase_dir }}`. Complete every remaining plan step, update the
replication log after each completion, download and validate required outputs,
apply the original output-attribution contract, and perform the original remote
shutdown procedure before returning.
