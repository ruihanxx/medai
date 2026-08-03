# medai

`medai` runs evidence-bound medical-paper replication and Auto Research
workflows in Docker. Every invocation explicitly selects `--replicate` or
`--autoresearch`. Replication mounts the paper, optional repository, and
optional local data read-only; Auto Research operates on a completed local run
without modifying its replication artifacts.

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
  --replicate \
  --paper /absolute/path/paper.pdf \
  --repo /absolute/path/repository \
  --data /absolute/path/data \
  --provider codex
```

On Windows, use the same arguments with `.\medai.cmd` instead of `./medai`.

```bash
./medai \
  --replicate \
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

To start or resume Auto Research from a completed replication run:

```bash
./medai \
  --autoresearch \
  --output runs/<run_id> \
  --max-iter 1
```

Auto Research restores the base inputs and provider configuration, skips
MinerU, and writes only below `runs/<run_id>/autoresearch/`. It creates three
isolated refinement candidates per round and runs code generation, audit,
planning, experimentation, and assessment for each candidate. A valid
refinement ends the loop after the current round; otherwise it continues up to
`--max-iter` (1-10). The base run must be completed and must describe a
supervised prediction task. The runtime also requires
`templates/skills/idea-generation/SKILL.md`; its absence is reported as an
explicit preflight failure.

Auto Research inherits the base provider, model, and reasoning effort unless
explicitly overridden. A `codex-siliconflow` campaign must receive
`--siliconflow-config` again because secrets are never restored from the base
manifest.

Supported providers are `claude`, `codex`, and `codex-siliconflow`. The latter
also requires `--siliconflow-config /path/to/provider.env`.

For the `codex` provider, set `MEDAI_CODEX_MODEL` and
`MEDAI_CODEX_REASONING_EFFORT` in `.env`, or override them with
`--codex-model` and `--codex-reasoning-effort`.

See [docs/project.md](docs/project.md) for the workflow and artifact contract.
