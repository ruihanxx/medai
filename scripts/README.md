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
