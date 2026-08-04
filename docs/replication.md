# Replication Workflow Contract

The LangGraph stages are:

1. `preflight`: validate inputs and record CPU, RAM, disk, and GPU resources.
2. `preprocess_pdf`: import the host MinerU result, convert it to canonical
   Markdown, and copy images. Host MinerU output remains temporary; only the
   canonical Markdown and artifacts persist in the run directory.
3. `preprocessing_agent`: audit `paper.md` in place by labeling linked
   Figure/Table assets with captions and correcting image-verified LaTeX,
   then write text/numeric claims and experiment definitions.
4. `codegen_agent`: inspect supplied data directly through bounded, read-only,
   non-executing reads, identify every paper-underspecified implementation
   decision before coding, resolve each using applicable medical knowledge and
   standard medical-research methods, record the executable resolution as a
   code-generation ambiguity, compare local GPU capacity with the paper's
   full-scale requirements, use the `computation-provider` skill to rent
   matching configured remote compute when needed, plan files, and write code.
5. `plan_agent`: check coverage, install dependencies, smoke-test, and write the
   replication plan.
6. `replicate_agent`: execute every experiment and write evidence.
7. `report_agents`: sequentially update one report with per-experiment
   claim/artifact comparisons, validation-anchor assessments, and a risk list
   derived from code-generation ambiguities.

Each workflow node prints `enter <stage> stage` to standard output immediately
when it starts.

There is no reduced-scale fallback. Missing evidence, invalid artifacts, or an
agent failure stops the run explicitly.

`manifest.json` is the canonical pipeline state. It records a versioned input
fingerprint, overall and per-stage status, attempts, timestamps, outputs, and
stage checkpoints. On reuse of an output directory, version 1 manifests are
migrated, the paper hash and output-affecting configuration must match, and
only stages marked `completed` are skipped. Every skipped stage reloads and
validates its canonical artifacts before downstream work proceeds. A `running`
or `failed` stage starts another attempt while retaining its writable artifacts.
Failure handling reloads the current manifest before recording the error so
stage updates are not overwritten by stale state. Code generation records
source preparation before invoking its agent; replication continues from the
valid ordered prefix in its step log; report generation checkpoints every
completed experiment. A completed run is therefore safe to invoke again and
becomes a validation-only no-op.
