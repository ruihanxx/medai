from __future__ import annotations

import argparse
import json
from pathlib import Path

from medai.resources import detect_resources

parser = argparse.ArgumentParser()
parser.add_argument("--path", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(
    json.dumps(detect_resources(args.path), indent=2) + "\n",
    encoding="utf-8",
)
