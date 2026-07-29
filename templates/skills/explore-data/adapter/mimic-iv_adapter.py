from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any

METADATA_PATH = Path(__file__).parents[1] / "metadata" / "mimic-iv.json"


class DatasetAdapter:
    def __init__(self, raw_root: str | Path):
        self.raw_root = Path(raw_root).expanduser().resolve()
        if not self.raw_root.is_dir():
            raise ValueError(f"Raw data directory does not exist: {self.raw_root}")
        self.metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    def list_resources(self) -> list[dict[str, Any]]:
        return list(self.metadata["files"])

    def sample(
        self,
        relative_path: str,
        limit: int = 5,
        max_field_chars: int = 512,
    ) -> dict[str, Any]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if max_field_chars < 1:
            raise ValueError("max_field_chars must be positive")

        resource = self._resource(relative_path)
        path = self._resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        result: dict[str, Any] = {
            "path": relative_path,
            "format": resource["format"],
            "compression": resource["compression"],
            "size_bytes": path.stat().st_size,
            "structure": resource["info"],
            "sample": None,
            "error": None,
        }
        if resource["format"] == "csv" and resource["compression"] == "gzip":
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames or []
                expected = resource["info"]["columns"]
                if columns != expected:
                    raise ValueError(
                        f"Header mismatch for {relative_path}: "
                        f"expected {expected}, observed {columns}"
                    )
                rows: list[dict[str, str]] = []
                fields_truncated = False
                for index, row in enumerate(reader):
                    if index >= limit:
                        break
                    sampled_row: dict[str, str] = {}
                    for column in columns:
                        value, truncated = self._truncate(
                            row.get(column, ""),
                            max_field_chars,
                        )
                        sampled_row[column] = value
                        fields_truncated = fields_truncated or truncated
                    rows.append(sampled_row)
            result["sample"] = {
                "rows": rows,
                "rows_returned": len(rows),
                "limit": limit,
                "fields_truncated": fields_truncated,
            }
            return result

        if resource["format"] == "text" and resource["compression"] is None:
            lines: list[str] = []
            fields_truncated = False
            with path.open(encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= limit:
                        break
                    value, truncated = self._truncate(
                        line.rstrip("\r\n"),
                        max_field_chars,
                    )
                    lines.append(value)
                    fields_truncated = fields_truncated or truncated
            result["sample"] = {
                "lines": lines,
                "lines_returned": len(lines),
                "limit": limit,
                "fields_truncated": fields_truncated,
            }
            return result

        raise ValueError(f"Unsupported MIMIC-IV resource format: {relative_path}")

    def build_inventory(
        self,
        selected_files: list[str] | None = None,
        rows: int = 5,
        max_field_chars: int = 512,
    ) -> dict[str, Any]:
        catalog: list[dict[str, Any]] = []
        files_scanned = 0
        bytes_scanned = 0
        warnings: list[str] = []

        for resource in self.list_resources():
            relative_path = self._relative_path(resource)
            path = self._resolve(relative_path)
            exists = path.is_file()
            size_bytes = path.stat().st_size if exists else None
            catalog.append(
                {
                    "path": relative_path,
                    "format": resource["format"],
                    "compression": resource["compression"],
                    "info": resource["info"],
                    "exists": exists,
                    "size_bytes": size_bytes,
                }
            )
            if exists:
                files_scanned += 1
                bytes_scanned += size_bytes or 0
            else:
                warnings.append(f"Catalog file is missing: {relative_path}")

        explored_files = [
            self.sample(
                relative_path,
                limit=rows,
                max_field_chars=max_field_chars,
            )
            for relative_path in (selected_files or [])
        ]
        return {
            "schema_version": 1,
            "dataset": {
                "id": self.metadata["dataset_id"],
                "root": str(self.raw_root),
                "adapter": "mimic-iv",
                "status": "explored",
            },
            "scan": {
                "files_scanned": files_scanned,
                "bytes_scanned": bytes_scanned,
                "truncated": False,
                "limits": {
                    "max_files": len(catalog),
                    "max_sampled_files": len(selected_files or []),
                    "rows_per_file": rows,
                    "max_field_chars": max_field_chars,
                },
            },
            "catalog": catalog,
            "explored_files": explored_files,
            "warnings": warnings,
        }

    def write_inventory(
        self,
        output: str | Path,
        selected_files: list[str] | None = None,
        rows: int = 5,
        max_field_chars: int = 512,
    ) -> dict[str, Any]:
        destination = Path(output).expanduser().resolve()
        if destination.is_relative_to(self.raw_root):
            raise ValueError("Inventory output must not be inside the raw data directory")
        payload = self.build_inventory(
            selected_files=selected_files,
            rows=rows,
            max_field_chars=max_field_chars,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return payload

    def _resource(self, relative_path: str) -> dict[str, Any]:
        normalized = Path(relative_path).as_posix()
        for resource in self.list_resources():
            if self._relative_path(resource) == normalized:
                return resource
        raise KeyError(f"Unknown MIMIC-IV file: {relative_path}")

    def _resolve(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Dataset file paths must be relative to the raw root")
        resolved = (self.raw_root / candidate).resolve()
        if not resolved.is_relative_to(self.raw_root):
            raise ValueError(f"Dataset file escapes the raw root: {relative_path}")
        return resolved

    @staticmethod
    def _relative_path(resource: dict[str, Any]) -> str:
        if resource["directory"] == ".":
            return resource["name"]
        return f"{resource['directory']}/{resource['name']}"

    @staticmethod
    def _truncate(value: str | None, max_chars: int) -> tuple[str, bool]:
        text = value or ""
        if len(text) <= max_chars:
            return text, False
        return text[:max_chars], True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a bounded, read-only MIMIC-IV data inventory."
    )
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--file", action="append", default=[], dest="selected_files")
    parser.add_argument("--rows", type=int, default=5)
    parser.add_argument("--max-field-chars", type=int, default=512)
    args = parser.parse_args()

    DatasetAdapter(args.raw_root).write_inventory(
        args.output,
        selected_files=args.selected_files,
        rows=args.rows,
        max_field_chars=args.max_field_chars,
    )


if __name__ == "__main__":
    main()
