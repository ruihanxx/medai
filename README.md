# medai

`medai` runs an evidence-bound medical-paper replication workflow in Docker.
The paper, optional repository, and optional local data are mounted read-only.
Each run writes to a unique directory under the repository-root `runs/`
directory; only that run directory is writable in the container.

Run MedAI from a source checkout because initialization builds its local Docker
overlay from that checkout. Initialize the image, host MinerU environment, and
models with one command. Docker Engine is required on Linux; macOS and Windows
use Docker Desktop, with Windows configured for Linux containers.

```bash
# Linux and macOS
./medai init
```

```bat
:: Windows Command Prompt or PowerShell
.\medai.cmd init
```

Initialization creates a dedicated Python environment under the model cache,
installs the pinned MinerU pipeline runtime, and downloads the models. MinerU
requires Python 3.10+. Supported desktop targets are Apple Silicon macOS 14+ and
x86_64 Windows; current PyTorch binaries do not support Intel macOS or Windows
ARM. Windows is limited to Python 3.10-3.12. On Apple Silicon, when the launcher
Python is not native arm64, `init` automatically uses or installs Homebrew's
native `python@3.12`. Native Homebrew itself must already be installed.
`MEDAI_MINERU_PYTHON` can select an explicit interpreter instead. For example:

```bash
MEDAI_MINERU_PYTHON=/opt/homebrew/bin/python3.12 ./medai init
```

PDF parsing runs natively on the host. The launcher detects CUDA, Apple MPS, or
CPU through the installed PyTorch runtime and defaults to MinerU's
cross-platform `pipeline` backend on every device. Set `MEDAI_MINERU_BACKEND`
to override that backend. On Windows or Linux NVIDIA systems that need a
CUDA-specific PyTorch wheel, set
`MEDAI_TORCH_INDEX_URL` to the index selected for the installed CUDA version
before running `init`.

Models and the Python environment are persisted outside disposable run
containers and reused for every paper. To resume an interrupted run, repeat the
same inputs and configuration and pass its existing run directory with
`--output`:

```bash
./medai \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex
```

On Windows, use the same arguments with `.\medai.cmd` instead of `./medai`.

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
