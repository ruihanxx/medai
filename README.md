# medai

`medai` runs an evidence-bound medical-paper replication workflow in Docker.
The paper, optional repository, and optional local data are mounted read-only.
Each run writes to a unique directory under the repository-root `runs/`
directory; only that run directory is writable in the container.

```bash
./medai \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex
```

Supported providers are `claude`, `codex`, and `codex-siliconflow`. The latter
also requires `--siliconflow-config /path/to/provider.env`.

For the `codex` provider, set `MEDAI_CODEX_MODEL` and
`MEDAI_CODEX_REASONING_EFFORT` in `.env`, or override them with
`--codex-model` and `--codex-reasoning-effort`.

See [docs/project.md](docs/project.md) for the workflow and artifact contract.
