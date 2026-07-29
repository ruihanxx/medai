from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("data_dir", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

if not args.data_dir.is_dir():
    raise SystemExit(f"Data directory does not exist: {args.data_dir}")

files = [path for path in args.data_dir.rglob("*") if path.is_file()]
extensions = Counter(path.suffix.casefold() or "<none>" for path in files)
samples = []
for path in sorted(files)[:20]:
    item = {
        "path": str(path.relative_to(args.data_dir)),
        "size_bytes": path.stat().st_size,
    }
    if path.suffix.casefold() in {".csv", ".tsv"} and path.stat().st_size <= 10 * 1024**2:
        delimiter = "\t" if path.suffix.casefold() == ".tsv" else ","
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                item["columns"] = next(csv.reader(handle, delimiter=delimiter))
        except (OSError, UnicodeDecodeError, StopIteration):
            item["columns"] = []
    samples.append(item)

payload = {
    "root": str(args.data_dir.resolve()),
    "file_count": len(files),
    "total_bytes": sum(path.stat().st_size for path in files),
    "extensions": dict(sorted(extensions.items())),
    "samples": samples,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
