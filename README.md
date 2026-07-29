# medai

`medai` runs an evidence-bound medical-paper replication workflow in Docker.
The paper, optional repository, and optional local data are mounted read-only.
Only the selected output directory is writable.

```bash
./medai \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex \
  --output /absolute/path/run
```

Supported providers are `claude`, `codex`, and `codex-siliconflow`. The latter
also requires `--siliconflow-config /path/to/provider.env`.

For the `codex` provider, set `MEDAI_CODEX_MODEL` and
`MEDAI_CODEX_REASONING_EFFORT` in `.env`, or override them with
`--codex-model` and `--codex-reasoning-effort`.

See [docs/project.md](docs/project.md) for the workflow and artifact contract.
