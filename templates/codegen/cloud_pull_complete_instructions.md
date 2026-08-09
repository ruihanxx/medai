# Cloud materialization complete

Local orchestration has completed cloud materialization. The completed,
read-only remote dataset is recorded in `{{ computation_provider_state_path }}`
and the instance has been returned to a running, SSH-ready state.

Continue the remaining code-generation work from the original instructions.
You may now inspect only the completed materialized remote dataset and must use
its recorded target path as `remote_dataset_dir`. Do not rematerialize the raw
cloud data or copy it locally.
