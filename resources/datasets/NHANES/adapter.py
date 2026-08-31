from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import importlib
import io
import json
from pathlib import Path
from typing import Any, Iterator

import yaml

XPT_HEADER_PREFIX = b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"
LARGE_TABLE_BYTES = 512 * 1024**2


class DatasetAdapterError(Exception):
    pass


class ResourceNotFoundError(DatasetAdapterError):
    pass


class ColumnNotFoundError(DatasetAdapterError):
    pass


class UnsupportedFormatError(DatasetAdapterError):
    pass


class DatasetAdapter:
    """Partition-aware access layer for the local Continuous NHANES capsule.

    Physical XPT files are indexed once in manifest.json. resources.yaml
    describes component collections rather than repeating 1,598 file records.
    XPT schemas remain file-specific and can be grouped by exact structure with
    group_shared_schemas().
    """

    def __init__(self, root: str | Path):
        root_path = Path(root)
        if root_path.name == "raw" and not (root_path / "resources.yaml").exists():
            root_path = root_path.parent
        self.root = root_path
        self.raw = self.root / "raw"
        self.resources_path = self.root / "resources.yaml"
        self.graph_path = self.root / "dataset_graph.yaml"
        self.manifest_path = self.root / "manifest.json"
        self.checksums_path = self.root / "SHA256SUMS"
        self.resources_doc = self._read_yaml(self.resources_path)
        self.graph_doc = self._read_yaml(self.graph_path)
        self.manifest_doc = self._read_json(self.manifest_path)
        self._resources = {
            resource["resource_id"]: resource
            for resource in self.resources_doc.get("resources", [])
        }
        self._files = list(self.manifest_doc.get("files", []))

    def describe(self) -> dict[str, Any]:
        cycles = self.list_cycles()
        return {
            "dataset_id": self.resources_doc.get("dataset_id"),
            "dataset_name": self.resources_doc.get("dataset_name"),
            "version": self.resources_doc.get("version"),
            "root": str(self.root),
            "raw_root": str(self.raw),
            "components": list(self.manifest_doc.get("components", [])),
            "cycles_with_public_xpt": cycles,
            "listed_cycles_without_public_xpt": list(
                self.manifest_doc.get("listed_cycles_without_public_xpt", [])
            ),
            "file_count": len(self._files),
            "size_bytes": sum(item.get("size_bytes", 0) for item in self._files),
            "complete": bool(self.manifest_doc.get("complete")),
            "privacy_note": (
                "preview() is schema-only. Row-level public-use participant data are "
                "returned only by explicit load_table()/iter_batches()/iter_rows() calls."
            ),
        }

    def list_resources(self) -> list[dict[str, Any]]:
        return list(self.resources_doc.get("resources", []))

    def list_cycles(
        self,
        resource_id: str | None = None,
        include_catalog_only: bool = False,
    ) -> list[str]:
        if resource_id is None:
            cycles = list(self.manifest_doc.get("cycles_with_public_xpt", []))
        else:
            resource = self._component_resource(resource_id)
            component = resource["component"]
            cycles = sorted(
                {item["cycle"] for item in self._files if item["component"] == component}
            )
        if include_catalog_only:
            for cycle in self.manifest_doc.get("listed_cycles_without_public_xpt", []):
                if cycle not in cycles:
                    cycles.append(cycle)
        return cycles

    def list_files(
        self,
        resource_id: str,
        cycles: str | list[str] | tuple[str, ...] | None = None,
        filename_patterns: str | list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        resource = self._component_resource(resource_id)
        component = resource["component"]
        selected_cycles = (
            set(self._normalize_cycles(cycles)) if cycles is not None else None
        )
        patterns = self._normalize_patterns(filename_patterns)
        selected = []
        for item in self._files:
            if item["component"] != component:
                continue
            if selected_cycles is not None and item["cycle"] not in selected_cycles:
                continue
            if patterns and not any(
                fnmatch.fnmatchcase(item["filename"].upper(), pattern.upper())
                for pattern in patterns
            ):
                continue
            selected.append(dict(item))
        return selected

    def get_resource_paths(
        self,
        resource_id: str,
        cycles: str | list[str] | tuple[str, ...] | None = None,
        filename_patterns: str | list[str] | tuple[str, ...] | None = None,
    ) -> list[Path]:
        resource = self._resource(resource_id)
        if resource.get("kind") == "component_xpt_collection":
            return [
                self.root / item["relative_path"]
                for item in self.list_files(
                    resource_id,
                    cycles=cycles,
                    filename_patterns=filename_patterns,
                )
            ]
        if cycles is not None or filename_patterns is not None:
            raise ResourceNotFoundError(
                f"filters apply only to component XPT collections: {resource_id}"
            )
        return [self.root / path for path in resource.get("paths", [])]

    def get_resource_path(
        self,
        resource_id: str,
        cycle: str | None = None,
        filename: str | None = None,
    ) -> Path:
        resource = self._resource(resource_id)
        if resource.get("kind") != "component_xpt_collection":
            paths = self.get_resource_paths(resource_id)
        else:
            if cycle is None or filename is None:
                raise ResourceNotFoundError(
                    "cycle and filename are required for a component XPT resource"
                )
            paths = self.get_resource_paths(
                resource_id,
                cycles=[cycle],
                filename_patterns=[filename],
            )
            paths = [path for path in paths if path.name.upper() == filename.upper()]
        if len(paths) != 1:
            raise ResourceNotFoundError(
                f"expected exactly one path for {resource_id}, found {len(paths)}"
            )
        return paths[0]

    def read_schema(
        self,
        resource_id: str,
        cycle: str,
        filename: str,
        encoding: str = "latin-1",
    ) -> dict[str, Any]:
        path = self.get_resource_path(resource_id, cycle, filename)
        schema = self._schema_from_path(path, encoding=encoding)
        return {
            "resource_id": resource_id,
            "cycle": cycle,
            "filename": path.name,
            "relative_path": str(path.relative_to(self.root)),
            **schema,
        }

    def group_shared_schemas(
        self,
        resource_id: str | None = None,
        cycles: str | list[str] | tuple[str, ...] | None = None,
        filename_patterns: str | list[str] | tuple[str, ...] | None = None,
        min_files: int = 2,
        encoding: str = "latin-1",
    ) -> list[dict[str, Any]]:
        """Group files by exact ordered (column name, SAS type, width) structure.

        Each returned group contains the structure once and a ``files`` list
        naming every physical XPT that shares it. Labels are excluded from the
        signature because wording can change without changing the table layout.
        """
        if min_files <= 0:
            raise ValueError("min_files must be greater than zero")
        resource_ids = (
            [resource_id]
            if resource_id is not None
            else [
                item["resource_id"]
                for item in self.list_resources()
                if item.get("kind") == "component_xpt_collection"
            ]
        )
        grouped: dict[str, dict[str, Any]] = {}
        for selected_resource_id in resource_ids:
            for item in self.list_files(
                selected_resource_id,
                cycles=cycles,
                filename_patterns=filename_patterns,
            ):
                path = self.root / item["relative_path"]
                schema = self._schema_from_path(path, encoding=encoding)
                structure = [
                    {
                        "name": variable["name"],
                        "type": variable["type"],
                        "length": variable["length"],
                    }
                    for variable in schema["variables"]
                ]
                serialized = json.dumps(structure, separators=(",", ":"), sort_keys=True)
                schema_id = hashlib.sha256(serialized.encode()).hexdigest()[:16]
                group = grouped.setdefault(
                    schema_id,
                    {
                        "schema_id": schema_id,
                        "columns": [variable["name"] for variable in structure],
                        "column_types": [
                            {"type": variable["type"], "length": variable["length"]}
                            for variable in structure
                        ],
                        "files": [],
                    },
                )
                group["files"].append(item["relative_path"])
        result = []
        for group in grouped.values():
            if len(group["files"]) < min_files:
                continue
            group["files"].sort()
            group["file_count"] = len(group["files"])
            result.append(group)
        return sorted(result, key=lambda group: (-group["file_count"], group["schema_id"]))

    def load_table(
        self,
        resource_id: str,
        cycle: str,
        filename: str,
        columns: list[str] | None = None,
        nrows: int | None = None,
        encoding: str = "latin-1",
        include_provenance: bool = True,
        allow_large: bool = False,
    ):
        """Load one explicitly selected XPT file as a pandas DataFrame."""
        if nrows is not None and nrows < 0:
            raise ValueError("nrows must be non-negative")
        path = self.get_resource_path(resource_id, cycle, filename)
        if nrows is None and path.stat().st_size > LARGE_TABLE_BYTES and not allow_large:
            raise DatasetAdapterError(
                f"refusing to materialize {path.stat().st_size} bytes without a bound; "
                "use iter_batches(), pass nrows, or set allow_large=True explicitly"
            )
        schema = self.read_schema(resource_id, cycle, filename, encoding=encoding)
        self._check_columns(resource_id, columns, schema["columns"])
        pd = self._require_pandas()
        if nrows == 0:
            frame = pd.DataFrame(columns=schema["columns"])
        elif nrows is None:
            frame = pd.read_sas(path, format="xport", encoding=encoding)
        else:
            reader = pd.read_sas(
                path,
                format="xport",
                encoding=encoding,
                iterator=True,
            )
            try:
                frame = reader.read(nrows)
            finally:
                reader.close()
        if columns is not None:
            frame = frame.loc[:, columns]
        if include_provenance:
            self._add_provenance(frame, cycle, path)
        return frame

    def iter_batches(
        self,
        resource_id: str,
        cycle: str,
        filename: str,
        columns: list[str] | None = None,
        batch_size: int = 10_000,
        limit: int | None = None,
        encoding: str = "latin-1",
        include_provenance: bool = True,
    ) -> Iterator[Any]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return
        path = self.get_resource_path(resource_id, cycle, filename)
        schema = self.read_schema(resource_id, cycle, filename, encoding=encoding)
        self._check_columns(resource_id, columns, schema["columns"])
        pd = self._require_pandas()
        reader = pd.read_sas(
            path,
            format="xport",
            encoding=encoding,
            iterator=True,
            chunksize=batch_size,
        )
        yielded = 0
        try:
            while limit is None or yielded < limit:
                size = batch_size if limit is None else min(batch_size, limit - yielded)
                try:
                    frame = reader.get_chunk(size)
                except StopIteration:
                    break
                if frame.empty:
                    break
                if columns is not None:
                    frame = frame.loc[:, columns]
                if include_provenance:
                    self._add_provenance(frame, cycle, path)
                yielded += len(frame)
                yield frame
        finally:
            reader.close()

    def iter_rows(
        self,
        resource_id: str,
        cycle: str,
        filename: str,
        columns: list[str] | None = None,
        limit: int | None = None,
        batch_size: int = 10_000,
        encoding: str = "latin-1",
        include_provenance: bool = True,
    ) -> Iterator[dict[str, Any]]:
        for frame in self.iter_batches(
            resource_id,
            cycle,
            filename,
            columns=columns,
            batch_size=batch_size,
            limit=limit,
            encoding=encoding,
            include_provenance=include_provenance,
        ):
            yield from frame.to_dict(orient="records")

    def preview(
        self,
        resource_id: str,
        cycle: str,
        filename: str,
        encoding: str = "latin-1",
    ) -> dict[str, Any]:
        path = self.get_resource_path(resource_id, cycle, filename)
        schema = self.read_schema(resource_id, cycle, filename, encoding=encoding)
        return {
            **schema,
            "size_bytes": path.stat().st_size,
            "preview_rows": [],
            "privacy_note": "Row-level values are omitted from preview.",
        }

    def validate(self, deep: bool = False) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})

        for filename in [
            "adapter.py",
            "resources.yaml",
            "dataset_graph.yaml",
            "manifest.json",
            "SHA256SUMS",
        ]:
            add(filename, (self.root / filename).is_file(), filename)

        expected_count = self.manifest_doc.get("file_count")
        complete_count = self.manifest_doc.get("complete_count")
        add(
            "manifest_complete",
            bool(self.manifest_doc.get("complete"))
            and expected_count == complete_count == len(self._files),
            f"manifest={expected_count}; complete={complete_count}; indexed={len(self._files)}",
        )

        relative_paths = [item["relative_path"] for item in self._files]
        add(
            "manifest_paths_unique",
            len(relative_paths) == len(set(relative_paths)),
            f"{len(relative_paths)} entries",
        )
        missing = [path for path in relative_paths if not (self.root / path).is_file()]
        add(
            "manifest_paths_exist",
            not missing,
            f"missing={len(missing)}" + (f"; first={missing[0]}" if missing else ""),
        )
        actual_xpt = list(self.raw.glob("*/*/*.xpt")) if self.raw.is_dir() else []
        add(
            "xpt_file_count",
            len(actual_xpt) == len(self._files),
            f"expected={len(self._files)}; observed={len(actual_xpt)}",
        )

        size_mismatches = []
        bad_headers = []
        for item in self._files:
            path = self.root / item["relative_path"]
            if not path.is_file():
                continue
            if path.stat().st_size != item.get("size_bytes"):
                size_mismatches.append(item["relative_path"])
            with path.open("rb") as handle:
                if handle.read(len(XPT_HEADER_PREFIX)) != XPT_HEADER_PREFIX:
                    bad_headers.append(item["relative_path"])
        add(
            "manifest_sizes",
            not size_mismatches,
            f"mismatches={len(size_mismatches)}",
        )
        add(
            "xpt_headers",
            not bad_headers,
            f"invalid={len(bad_headers)}",
        )

        checksum_index = self._read_checksum_index()
        expected_checksums = {
            item["relative_path"]: item["sha256"] for item in self._files
        }
        add(
            "checksum_index",
            checksum_index == expected_checksums,
            f"manifest={len(expected_checksums)}; SHA256SUMS={len(checksum_index)}",
        )

        for resource_id, resource in self._resources.items():
            if resource.get("kind") != "component_xpt_collection":
                continue
            count = len(self.list_files(resource_id))
            expected = resource.get("count_summary", {}).get("file_count")
            add(
                f"{resource_id}_file_count",
                count == expected,
                f"expected={expected}; observed={count}",
            )

        graph_entities = {
            entity["entity_id"]: entity for entity in self.graph_doc.get("entities", [])
        }
        graph_resources = {
            resource_id
            for entity in graph_entities.values()
            for resource_id in entity.get("resource_ids", [])
        }
        unknown_graph_resources = sorted(graph_resources - set(self._resources))
        add(
            "dataset_graph_resources",
            not unknown_graph_resources,
            (
                f"unknown={unknown_graph_resources}"
                if unknown_graph_resources
                else "all graph resources resolve"
            ),
        )
        unknown_endpoints = sorted(
            {
                endpoint
                for relationship in self.graph_doc.get("relationships", [])
                for endpoint in [
                    relationship.get("from_entity"),
                    relationship.get("to_entity"),
                ]
                if endpoint not in graph_entities
            }
        )
        add(
            "dataset_graph_relationships",
            not unknown_endpoints,
            (
                f"unknown={unknown_endpoints}"
                if unknown_endpoints
                else "all relationship endpoints resolve"
            ),
        )

        if deep:
            digest_mismatches = []
            for item in self._files:
                path = self.root / item["relative_path"]
                if path.is_file() and self._sha256(path) != item["sha256"]:
                    digest_mismatches.append(item["relative_path"])
            add(
                "xpt_sha256",
                not digest_mismatches,
                f"mismatches={len(digest_mismatches)}",
            )

        _, pandas_error = self._try_import_pandas()
        if pandas_error:
            warnings.append(
                {
                    "name": "pandas_import",
                    "detail": (
                        "pandas is required for XPT schema and row access: "
                        f"{pandas_error}"
                    ),
                }
            )
        return {
            "ok": all(check["ok"] for check in checks),
            "checks": checks,
            "warnings": warnings,
        }

    def _resource(self, resource_id: str) -> dict[str, Any]:
        resource = self._resources.get(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"unknown resource_id: {resource_id}")
        return resource

    def _component_resource(self, resource_id: str) -> dict[str, Any]:
        resource = self._resource(resource_id)
        if resource.get("kind") != "component_xpt_collection":
            raise ResourceNotFoundError(
                f"resource is not a component XPT collection: {resource_id}"
            )
        return resource

    def _normalize_cycles(
        self,
        cycles: str | list[str] | tuple[str, ...],
    ) -> list[str]:
        selected = [cycles] if isinstance(cycles, str) else list(cycles)
        known = set(self.list_cycles(include_catalog_only=True)) | {"2019-2020"}
        normalized = []
        for cycle in selected:
            if cycle not in known:
                raise ValueError(f"unknown NHANES cycle: {cycle}")
            if cycle not in normalized:
                normalized.append(cycle)
        return normalized

    @staticmethod
    def _normalize_patterns(
        patterns: str | list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        if patterns is None:
            return []
        return [patterns] if isinstance(patterns, str) else list(patterns)

    def _schema_from_path(self, path: Path, encoding: str) -> dict[str, Any]:
        pd = self._require_pandas()
        reader = pd.read_sas(
            path,
            format="xport",
            encoding=encoding,
            iterator=True,
        )
        try:
            variables = []
            for field in reader.fields:
                name = self._decode_xpt_text(field.get("name"), encoding)
                variables.append(
                    {
                        "name": name,
                        "type": field.get("ntype"),
                        "length": field.get("field_length"),
                        "label": self._decode_xpt_text(field.get("label"), encoding),
                    }
                )
            return {
                "row_count": reader.nobs,
                "column_count": len(variables),
                "columns": [variable["name"] for variable in variables],
                "variables": variables,
            }
        finally:
            reader.close()

    @staticmethod
    def _decode_xpt_text(value: Any, encoding: str) -> str:
        if isinstance(value, bytes):
            return value.decode(encoding, "replace").rstrip("\x00 ")
        return str(value or "").rstrip("\x00 ")

    @staticmethod
    def _check_columns(
        resource_id: str,
        requested: list[str] | None,
        available: list[str],
    ) -> None:
        if requested is None:
            return
        missing = [column for column in requested if column not in available]
        if missing:
            raise ColumnNotFoundError(
                f"resource {resource_id} missing requested columns: {missing}"
            )

    def _add_provenance(self, frame: Any, cycle: str, path: Path) -> None:
        frame.insert(0, "_source_file", str(path.relative_to(self.root)))
        frame.insert(0, "_cycle", cycle)

    def _read_checksum_index(self) -> dict[str, str]:
        if not self.checksums_path.is_file():
            return {}
        checksums = {}
        with self.checksums_path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                digest, relative_path = stripped.split(maxsplit=1)
                checksums[relative_path.lstrip("* ")] = digest
        return checksums

    def _require_pandas(self):
        pd, error = self._try_import_pandas()
        if pd is None:
            raise UnsupportedFormatError(
                "pandas with SAS XPORT support is required to inspect or read NHANES XPT files"
            ) from error
        return pd

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise DatasetAdapterError(f"missing required file: {path}")
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise DatasetAdapterError(f"missing required file: {path}")
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _try_import_pandas():
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                return importlib.import_module("pandas"), None
        except Exception as exc:  # noqa: BLE001 - optional dependency may fail broadly.
            detail = str(exc) or exc.__class__.__name__
            return None, detail


__all__ = [
    "ColumnNotFoundError",
    "DatasetAdapter",
    "DatasetAdapterError",
    "ResourceNotFoundError",
    "UnsupportedFormatError",
]
