from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib
import io
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

import yaml

QUARTER_RE = re.compile(r"^(?P<year>[0-9]{4})Q(?P<quarter>[1-4])$")
TABLE_FILE_RE = re.compile(
    r"^(?P<table>DEMO|DRUG|INDI|OUTC|REAC|RPSR|THER)"
    r"(?P<year>[0-9]{2})Q(?P<quarter>[1-4])(?:_NEW)?[.]TXT$",
    re.IGNORECASE,
)


class DatasetAdapterError(Exception):
    pass


class ResourceNotFoundError(DatasetAdapterError):
    pass


class ColumnNotFoundError(DatasetAdapterError):
    pass


class DatasetAdapter:
    """Partition-aware access layer for the local FAERS ASCII extracts.

    The seven logical tables are described once in resources.yaml and resolved
    across quarter directories at runtime. Raw 2014Q1-Q2 schema differences are
    normalized to the 2014Q3+ column contract without inventing values: fields
    absent in the older release are returned as ``None``.
    """

    def __init__(self, root: str | Path):
        root_path = Path(root)
        if root_path.name == "raw" and not (root_path / "resources.yaml").exists():
            root_path = root_path.parent
        self.root = root_path
        self.raw = self.root / "raw"
        self.resources_path = self.root / "resources.yaml"
        self.graph_path = self.root / "dataset_graph.yaml"
        self.resources_doc = self._read_yaml(self.resources_path)
        self.graph_doc = self._read_yaml(self.graph_path)
        self._resources = {
            resource["resource_id"]: resource
            for resource in self.resources_doc.get("resources", [])
        }

    def describe(self) -> dict[str, Any]:
        quarters = self.list_quarters()
        return {
            "dataset_id": self.resources_doc.get("dataset_id"),
            "dataset_name": self.resources_doc.get("dataset_name"),
            "version": self.resources_doc.get("version"),
            "root": str(self.root),
            "raw_root": str(self.raw),
            "quarter_count": len(quarters),
            "quarter_range": [quarters[0], quarters[-1]] if quarters else [],
            "resource_count": len(self._resources),
            "logical_table_count": sum(
                resource.get("kind") == "quarterly_table" for resource in self._resources.values()
            ),
            "delimiter": "$",
            "privacy_note": (
                "preview() is schema-only; row-level adverse-event reports are not "
                "returned unless load_table(), iter_rows(), or iter_batches() is called."
            ),
        }

    def list_resources(self) -> list[dict[str, Any]]:
        return list(self.resources_doc.get("resources", []))

    def list_quarters(self) -> list[str]:
        if not self.raw.exists():
            return []
        return sorted(
            path.name
            for path in self.raw.iterdir()
            if path.is_dir() and QUARTER_RE.fullmatch(path.name)
        )

    def get_resource_paths(
        self,
        resource_id: str,
        quarters: str | list[str] | tuple[str, ...] | None = None,
    ) -> list[Path]:
        resource = self._resource(resource_id)
        kind = resource.get("kind")
        selected = self._normalize_quarters(quarters)

        if kind == "quarterly_table":
            return [self.get_resource_path(resource_id, quarter) for quarter in selected]
        if kind == "deleted_case_list":
            paths: list[Path] = []
            for quarter in selected:
                extracted = self.raw / quarter / "extracted"
                if extracted.exists():
                    paths.extend(
                        path
                        for path in extracted.rglob("*")
                        if path.is_file()
                        and path.suffix.lower() == ".txt"
                        and "delet" in path.as_posix().lower()
                    )
            return sorted(paths)
        if kind == "quarterly_archive":
            paths = []
            for quarter in selected:
                paths.extend((self.raw / quarter).glob("faers_ascii_*.zip"))
            return sorted(paths)
        if kind == "quarterly_documentation":
            paths = []
            for quarter in selected:
                extracted = self.raw / quarter / "extracted"
                if extracted.exists():
                    paths.extend(
                        path
                        for path in extracted.rglob("*")
                        if path.is_file() and path.suffix.lower() in {".doc", ".pdf"}
                    )
            return sorted(paths)
        if kind == "acquisition_support":
            return [self.root / path for path in resource.get("paths", [])]
        raise ResourceNotFoundError(f"unsupported resource kind for {resource_id}: {kind}")

    def get_resource_path(self, resource_id: str, quarter: str) -> Path:
        resource = self._resource(resource_id)
        if resource.get("kind") != "quarterly_table":
            raise ResourceNotFoundError(
                f"resource {resource_id} is not a single-file quarterly table"
            )
        self._validate_quarter(quarter)
        code = resource["table_code"]
        expected_year = quarter[2:4]
        expected_quarter = quarter[-1]
        extracted = self.raw / quarter / "extracted"
        matches = []
        if extracted.exists():
            for path in extracted.rglob("*"):
                if not path.is_file():
                    continue
                match = TABLE_FILE_RE.fullmatch(path.name)
                if (
                    match
                    and match.group("table").upper() == code
                    and match.group("year") == expected_year
                    and match.group("quarter") == expected_quarter
                ):
                    matches.append(path)
        if len(matches) != 1:
            raise ResourceNotFoundError(
                f"expected exactly one {code} table for {quarter}, found {len(matches)}"
            )
        return matches[0]

    def read_header(
        self,
        resource_id: str,
        quarter: str,
        normalize_schema: bool = True,
    ) -> list[str]:
        path = self.get_resource_path(resource_id, quarter)
        with path.open("r", encoding="latin-1", newline="") as handle:
            header = next(csv.reader(handle, delimiter="$"))
        if not normalize_schema:
            return header
        return list(self._resource(resource_id).get("canonical_columns", header))

    def load_table(
        self,
        resource_id: str,
        quarter: str,
        columns: list[str] | None = None,
        nrows: int | None = None,
        normalize_schema: bool = True,
        include_quarter: bool = True,
        as_dataframe: bool = True,
        **kwargs: Any,
    ):
        """Load one explicitly selected quarter.

        Cross-quarter access is intentionally streaming through iter_rows() or
        iter_batches() so that multi-gigabyte tables are not materialized by
        accident.
        """
        if nrows is not None and nrows < 0:
            raise ValueError("nrows must be non-negative")
        resource = self._resource(resource_id)
        if resource.get("kind") != "quarterly_table":
            raise ResourceNotFoundError(f"resource is not tabular: {resource_id}")
        canonical = list(resource.get("canonical_columns", []))
        if normalize_schema and columns is not None:
            self._check_columns(resource_id, columns, canonical)

        if as_dataframe:
            pd, _ = self._try_import_pandas()
            if pd is not None:
                reserved = {
                    "delimiter",
                    "dtype",
                    "encoding",
                    "keep_default_na",
                    "nrows",
                    "sep",
                }
                conflicts = sorted(reserved.intersection(kwargs))
                if conflicts:
                    raise TypeError(
                        "load_table controls these reader arguments directly: "
                        + ", ".join(conflicts)
                    )
                frame = pd.read_csv(
                    self.get_resource_path(resource_id, quarter),
                    sep="$",
                    encoding="latin-1",
                    dtype=str,
                    keep_default_na=False,
                    nrows=nrows,
                    **kwargs,
                )
                if normalize_schema:
                    frame = self._normalize_frame(resource_id, frame, canonical, pd)
                if columns is not None:
                    self._check_columns(resource_id, columns, list(frame.columns))
                    frame = frame.loc[:, columns]
                if include_quarter:
                    frame.insert(0, "_quarter", quarter)
                return frame

        return list(
            self.iter_rows(
                resource_id,
                quarters=[quarter],
                columns=columns,
                limit=nrows,
                normalize_schema=normalize_schema,
                include_quarter=include_quarter,
            )
        )

    def iter_rows(
        self,
        resource_id: str,
        quarters: str | list[str] | tuple[str, ...] | None = None,
        columns: list[str] | None = None,
        limit: int | None = None,
        normalize_schema: bool = True,
        include_quarter: bool = True,
    ) -> Iterator[dict[str, str | None]]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return
        resource = self._resource(resource_id)
        if resource.get("kind") != "quarterly_table":
            raise ResourceNotFoundError(f"resource is not tabular: {resource_id}")
        canonical = list(resource.get("canonical_columns", []))
        if normalize_schema and columns is not None:
            self._check_columns(resource_id, columns, canonical)

        yielded = 0
        for quarter in self._normalize_quarters(quarters):
            path = self.get_resource_path(resource_id, quarter)
            with path.open("r", encoding="latin-1", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="$", restkey="_extra_fields")
                raw_header = list(reader.fieldnames or [])
                if columns is not None and not normalize_schema:
                    self._check_columns(resource_id, columns, raw_header)
                for raw_row in reader:
                    if raw_row.get("_extra_fields"):
                        raise DatasetAdapterError(f"row contains extra delimited fields in {path}")
                    raw_row.pop("_extra_fields", None)
                    row = (
                        self._normalize_row(resource_id, raw_row, canonical)
                        if normalize_schema
                        else dict(raw_row)
                    )
                    if columns is not None:
                        row = {column: row.get(column) for column in columns}
                    if include_quarter:
                        row = {"_quarter": quarter, **row}
                    yield row
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return

    def iter_batches(
        self,
        resource_id: str,
        quarters: str | list[str] | tuple[str, ...] | None = None,
        columns: list[str] | None = None,
        batch_size: int = 10_000,
        limit: int | None = None,
        normalize_schema: bool = True,
        include_quarter: bool = True,
        as_dataframe: bool = True,
    ) -> Iterator[Any]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        pd, _ = self._try_import_pandas() if as_dataframe else (None, None)
        batch: list[dict[str, str | None]] = []
        for row in self.iter_rows(
            resource_id,
            quarters=quarters,
            columns=columns,
            limit=limit,
            normalize_schema=normalize_schema,
            include_quarter=include_quarter,
        ):
            batch.append(row)
            if len(batch) == batch_size:
                yield pd.DataFrame(batch) if pd is not None else batch
                batch = []
        if batch:
            yield pd.DataFrame(batch) if pd is not None else batch

    def iter_deleted_case_ids(
        self,
        quarters: str | list[str] | tuple[str, ...] | None = None,
        include_historical: bool = False,
    ) -> Iterator[dict[str, str]]:
        for path in self.get_resource_paths("deleted_cases", quarters=quarters):
            if not include_historical and path.name.lower() == "alldeletedcases.txt":
                continue
            quarter = next(part for part in path.parts if QUARTER_RE.fullmatch(part))
            with path.open("r", encoding="latin-1") as handle:
                for line in handle:
                    caseid = line.strip()
                    if caseid:
                        yield {
                            "_quarter": quarter,
                            "caseid": caseid,
                            "source_file": str(path.relative_to(self.root)),
                        }

    def preview(self, resource_id: str, quarter: str | None = None) -> dict[str, Any]:
        resource = self._resource(resource_id)
        if resource.get("kind") == "quarterly_table":
            selected = quarter or self.list_quarters()[-1]
            path = self.get_resource_path(resource_id, selected)
            return {
                "resource_id": resource_id,
                "quarter": selected,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "raw_columns": self.read_header(resource_id, selected, normalize_schema=False),
                "canonical_columns": self.read_header(resource_id, selected),
                "preview_rows": [],
                "privacy_note": "Row-level values are omitted from preview.",
            }
        paths = self.get_resource_paths(resource_id, quarters=[quarter] if quarter else None)
        return {
            "resource_id": resource_id,
            "path_count": len(paths),
            "paths": [str(path) for path in paths[:10]],
            "paths_truncated": len(paths) > 10,
        }

    def validate(self, deep: bool = False) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})

        for filename in ["adapter.py", "resources.yaml", "dataset_graph.yaml"]:
            add(filename, (self.root / filename).is_file(), filename)
        expected_quarters = self._quarters_for_group("all_quarters")
        actual_quarters = self.list_quarters()
        add(
            "quarter_partitions",
            actual_quarters == expected_quarters,
            f"expected {len(expected_quarters)}; found {len(actual_quarters)}",
        )
        graph_entities = {
            entity["entity_id"]: entity for entity in self.graph_doc.get("entities", [])
        }
        graph_resource_ids = {
            resource_id
            for entity in graph_entities.values()
            for resource_id in entity.get("resource_ids", [])
        }
        unknown_graph_resources = sorted(graph_resource_ids - set(self._resources))
        add(
            "dataset_graph_resources",
            not unknown_graph_resources,
            (
                f"unknown resource IDs: {unknown_graph_resources}"
                if unknown_graph_resources
                else "all graph resources resolve"
            ),
        )
        unknown_relationship_entities = sorted(
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
            not unknown_relationship_entities,
            (
                f"unknown entity IDs: {unknown_relationship_entities}"
                if unknown_relationship_entities
                else "all relationship endpoints resolve"
            ),
        )

        for resource_id, resource in self._resources.items():
            kind = resource.get("kind")
            if kind == "quarterly_table":
                paths: list[Path] = []
                headers_ok = True
                details: list[str] = []
                for quarter in expected_quarters:
                    try:
                        path = self.get_resource_path(resource_id, quarter)
                        paths.append(path)
                        observed = self.read_header(resource_id, quarter, normalize_schema=False)
                        expected = self._expected_raw_header(resource, quarter)
                        if observed != expected:
                            headers_ok = False
                            details.append(f"{quarter} header mismatch")
                    except Exception as exc:  # noqa: BLE001 - aggregate validation.
                        headers_ok = False
                        details.append(f"{quarter}: {exc}")
                add(
                    f"{resource_id}_files",
                    len(paths) == len(expected_quarters),
                    f"{len(paths)} quarterly files",
                )
                add(
                    f"{resource_id}_headers",
                    headers_ok,
                    "; ".join(details) if details else "all raw headers match declared variants",
                )
            elif kind == "deleted_case_list":
                paths = self.get_resource_paths(resource_id)
                add(
                    f"{resource_id}_files",
                    len(paths) == resource["count_summary"]["file_count"],
                    f"{len(paths)} files",
                )
            elif kind in {"quarterly_archive", "quarterly_documentation"}:
                paths = self.get_resource_paths(resource_id)
                add(
                    f"{resource_id}_files",
                    len(paths) == resource["count_summary"]["file_count"],
                    f"{len(paths)} files",
                )
            elif kind == "acquisition_support":
                paths = self.get_resource_paths(resource_id)
                add(
                    f"{resource_id}_files",
                    all(path.is_file() for path in paths),
                    f"{sum(path.is_file() for path in paths)}/{len(paths)} files",
                )

        if deep:
            archives = self.get_resource_paths("quarterly_archives")
            bad_archives = []
            for archive in archives:
                try:
                    with zipfile.ZipFile(archive) as handle:
                        bad_member = handle.testzip()
                    if bad_member is not None:
                        bad_archives.append(f"{archive.name}:{bad_member}")
                except Exception as exc:  # noqa: BLE001 - aggregate validation.
                    bad_archives.append(f"{archive.name}:{exc}")
            add(
                "quarterly_archive_integrity",
                not bad_archives,
                "; ".join(bad_archives) if bad_archives else "all ZIP members passed CRC",
            )
            checksum_failures = self._verify_checksums()
            add(
                "quarterly_archive_sha256",
                not checksum_failures,
                "; ".join(checksum_failures) if checksum_failures else "all SHA-256 entries match",
            )

        _, pandas_error = self._try_import_pandas()
        if pandas_error:
            warnings.append(
                {
                    "name": "pandas_import",
                    "detail": f"stdlib streaming remains available: {pandas_error}",
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

    def _normalize_quarters(
        self,
        quarters: str | list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        if quarters is None:
            selected = self.list_quarters()
        elif isinstance(quarters, str):
            selected = [quarters]
        else:
            selected = list(quarters)
        available = set(self.list_quarters())
        normalized: list[str] = []
        for quarter in selected:
            self._validate_quarter(quarter)
            if quarter not in available:
                raise ResourceNotFoundError(f"quarter not present locally: {quarter}")
            if quarter not in normalized:
                normalized.append(quarter)
        return normalized

    @staticmethod
    def _validate_quarter(quarter: str) -> None:
        if not QUARTER_RE.fullmatch(quarter):
            raise ValueError(f"invalid quarter: {quarter}; expected YYYYQn form such as 2024Q4")

    def _quarters_for_group(self, group_name: str) -> list[str]:
        groups = self.resources_doc.get("quarter_groups", {})
        group = groups.get(group_name)
        if group is None:
            raise DatasetAdapterError(f"unknown quarter group: {group_name}")
        if "quarters" in group:
            return list(group["quarters"])
        selector = group.get("selector")
        if not isinstance(selector, str) or ".." not in selector:
            raise DatasetAdapterError(f"invalid quarter selector for {group_name}")
        start, end = selector.split("..", 1)
        self._validate_quarter(start)
        self._validate_quarter(end)
        start_index = int(start[:4]) * 4 + int(start[-1]) - 1
        end_index = int(end[:4]) * 4 + int(end[-1]) - 1
        return [f"{index // 4}Q{index % 4 + 1}" for index in range(start_index, end_index + 1)]

    def _expected_raw_header(self, resource: dict[str, Any], quarter: str) -> list[str]:
        for variant in resource.get("raw_schema_variants", []):
            if quarter in self._quarters_for_group(variant["applies_to"]):
                return list(variant["columns"])
        raise DatasetAdapterError(
            f"no declared raw schema for {resource['resource_id']} in {quarter}"
        )

    @staticmethod
    def _check_columns(resource_id: str, requested: list[str], available: list[str]) -> None:
        missing = [column for column in requested if column not in available]
        if missing:
            raise ColumnNotFoundError(
                f"resource {resource_id} missing requested columns: {missing}"
            )

    @staticmethod
    def _normalize_row(
        resource_id: str,
        row: dict[str, str | None],
        canonical: list[str],
    ) -> dict[str, str | None]:
        normalized = dict(row)
        if resource_id == "demographics" and "sex" not in normalized:
            normalized["sex"] = normalized.pop("gndr_cod", None)
        return {column: normalized.get(column) for column in canonical}

    @staticmethod
    def _normalize_frame(resource_id: str, frame: Any, canonical: list[str], pd: Any):
        if (
            resource_id == "demographics"
            and "sex" not in frame.columns
            and "gndr_cod" in frame.columns
        ):
            frame = frame.rename(columns={"gndr_cod": "sex"})
        for column in canonical:
            if column not in frame.columns:
                frame[column] = pd.NA
        return frame.loc[:, canonical]

    def _verify_checksums(self) -> list[str]:
        manifest = self.raw / "SHA256SUMS"
        if not manifest.is_file():
            return ["raw/SHA256SUMS missing"]
        failures = []
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                expected, relative = line.rstrip("\n").split(maxsplit=1)
                relative = relative.lstrip("* ")
                path = self.raw / relative
                if not path.is_file():
                    failures.append(f"missing:{relative}")
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    failures.append(f"mismatch:{relative}")
        return failures

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise DatasetAdapterError(f"missing required file: {path}")
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

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
]
