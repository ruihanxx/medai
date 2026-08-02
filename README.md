# medai

`medai` runs an evidence-bound medical-paper replication workflow in Docker.
The paper, optional repository, and optional local data are mounted read-only.
Each run writes to a unique directory under the repository-root `runs/`
directory; only that run directory is writable in the container.

Initialize the Docker image and MinerU models once before the first run:

```bash
./medai init
```

The models are persisted outside disposable run containers and reused for
every paper. To resume an interrupted run, repeat the same inputs and
configuration and pass its existing run directory with `--output`:

```bash
./medai \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex
```

```bash
./medai \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex \
  --output runs/<run_id>
```

Completed stages are revalidated and skipped. An interrupted stage resumes as
a new attempt against its persisted artifacts; report generation also resumes
after its last completed experiment. MedAI rejects resume when the paper,
input paths, provider/model, reasoning effort, or smart-replication setting no
longer matches the recorded run.

Supported providers are `claude`, `codex`, and `codex-siliconflow`. The latter
also requires `--siliconflow-config /path/to/provider.env`.

For the `codex` provider, set `MEDAI_CODEX_MODEL` and
`MEDAI_CODEX_REASONING_EFFORT` in `.env`, or override them with
`--codex-model` and `--codex-reasoning-effort`.

See [docs/project.md](docs/project.md) for the workflow and artifact contract.
