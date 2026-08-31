# Scripts

## `generate_run_graph.py`

Generate a self-contained interactive graph from a MedAI manifest v6 run:

```bash
python scripts/generate_run_graph.py runs/<run_id>
```

The command reads canonical run artifacts without changing them and writes
`visualization/index.html` plus the audited snapshot `visualization/run_graph.json`.
Use `--open` to open the page, or `--output-dir <path>` to select another output
directory.

## `download_nhanes.py`

Download all CDC-listed public-use Continuous NHANES SAS transport files whose
cycle overlaps 1999-2026:

```bash
python scripts/download_nhanes.py
```

Files are organized beneath `resources/datasets/NHANES/raw/` by release cycle
and component. The downloader is concurrent and resumable, validates the SAS
XPORT header, and writes `manifest.json` plus `SHA256SUMS`. It records any
officially listed cycle that does not yet have public XPT files. Use `--jobs N`
to change normal-file concurrency, `--large-file-jobs N` to change resumable
HTTP-range concurrency for files larger than 1 GiB, or `--list-only` to refresh
only the official catalog.
