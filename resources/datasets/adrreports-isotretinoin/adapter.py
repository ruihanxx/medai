from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib
import io
import json
from pathlib import Path
from typing import Any, Iterator

import yaml

LINE_LISTING_RESOURCE_ID = "isotretinoin_line_listing"
SOURCE_YEAR_COLUMN = "source_year_bucket"
EU_LOCAL_NUMBER_COLUMN = "EU Local Number"
GATEWAY_DATE_COLUMN = "EV Gateway Receipt Date"


class DatasetAdapterError(Exception):
    pass


class ResourceNotFoundError(DatasetAdapterError):
    pass


class ColumnNotFoundError(DatasetAdapterError):
    pass


class UnsupportedFormatError(DatasetAdapterError):
    pass


class DatasetAdapter:
    """Partition-aware access to the isotretinoin ADRReports snapshot.

    ``resources.yaml`` declares the 36,039-row result set exactly once. The
    annual exports and the unpartitioned official export are equivalent source
    representations recorded by the acquisition manifest, not additional
    logical resources. Annual reads add the same ``source_year_bucket``
    provenance column found in the canonical combined CSV.
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
        self.resources_doc = self._read_yaml(self.resources_path)
        self.graph_doc = self._read_yaml(self.graph_path)
        self.manifest_doc = self._read_json(self.manifest_path)

        resources = list(self.resources_doc.get("resources", []))
        resource_ids = [resource.get("resource_id") for resource in resources]
        if None in resource_ids or len(resource_ids) != len(set(resource_ids)):
            raise DatasetAdapterError(
                "resources.yaml contains missing or duplicate resource_id values"
            )
        self._resources = {resource["resource_id"]: resource for resource in resources}

    def describe(self) -> dict[str, Any]:
        populated_years = self.list_years()
        annual = list(self.manifest_doc.get("annual", []))
        minimum_dates = [
            item["min_gateway_receipt_date"]
            for item in annual
            if item.get("min_gateway_receipt_date")
        ]
        maximum_dates = [
            item["max_gateway_receipt_date"]
            for item in annual
            if item.get("max_gateway_receipt_date")
        ]
        return {
            "dataset_id": self.resources_doc.get("dataset_id"),
            "dataset_name": self.resources_doc.get("dataset_name"),
            "version": self.resources_doc.get("version"),
            "root": str(self.root),
            "raw_root": str(self.raw),
            "resource_count": len(self._resources),
            "canonical_case_count": self.manifest_doc.get("records"),
            "official_column_count": self.manifest_doc.get("official_columns"),
            "canonical_column_count": len(self.read_header()),
            "populated_year_count": len(populated_years),
            "populated_year_range": [populated_years[0], populated_years[-1]]
            if populated_years
            else [],
            "gateway_receipt_date_range": [min(minimum_dates), max(maximum_dates)]
            if minimum_dates
            else [],
            "source_data_current_through": self.manifest_doc.get("source_data_current_through"),
            "deduplication_note": (
                "Annual and unpartitioned exports are alternate representations of "
                "isotretinoin_line_listing, not additional result resources."
            ),
            "privacy_note": (
                "preview() is schema-only. Use iter_rows(), iter_batches(), or "
                "load_table() explicitly to inspect public case-level rows."
            ),
        }

    def list_resources(self) -> list[dict[str, Any]]:
        return list(self.resources_doc.get("resources", []))

    def list_partitions(self, include_empty: bool = False) -> list[dict[str, Any]]:
        partitions = sorted(self.manifest_doc.get("annual", []), key=lambda item: int(item["year"]))
        if include_empty:
            return partitions
        return [item for item in partitions if int(item.get("records", 0)) > 0]

    def list_years(self, include_empty: bool = False) -> list[int]:
        return [int(item["year"]) for item in self.list_partitions(include_empty)]

    def get_resource_path(self, resource_id: str = LINE_LISTING_RESOURCE_ID) -> Path:
        resource = self._resource(resource_id)
        paths = resource.get("paths") or []
        if len(paths) != 1:
            raise ResourceNotFoundError(
                f"resource {resource_id} does not resolve to exactly one canonical path"
            )
        return self.root / paths[0]

    def get_partition_path(self, year: int | str) -> Path:
        normalized_year = self._normalize_year(year)
        for partition in self.list_partitions(include_empty=True):
            if int(partition["year"]) == normalized_year:
                return self.root / partition["raw_file"]
        raise ResourceNotFoundError(f"unknown source year bucket: {normalized_year}")

    def read_header(
        self,
        resource_id: str = LINE_LISTING_RESOURCE_ID,
        year: int | str | None = None,
    ) -> list[str]:
        self._require_tabular_resource(resource_id)
        path = (
            self.get_partition_path(year)
            if year is not None
            else self.get_resource_path(resource_id)
        )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle))

    def check_columns(self, columns: list[str]) -> None:
        header = self.read_header()
        missing = [column for column in columns if column not in header]
        if missing:
            raise ColumnNotFoundError(f"line listing missing requested columns: {missing}")

    def load_table(
        self,
        resource_id: str = LINE_LISTING_RESOURCE_ID,
        columns: list[str] | None = None,
        years: int | str | list[int | str] | tuple[int | str, ...] | None = None,
        parse_dates: bool | list[str] = False,
        nrows: int | None = None,
        as_dataframe: bool = True,
        **kwargs: Any,
    ):
        """Load the canonical snapshot or explicitly selected annual partitions."""
        self._require_tabular_resource(resource_id)
        if nrows is not None and nrows < 0:
            raise ValueError("nrows must be non-negative")
        if columns is not None:
            self.check_columns(columns)
        selected_years = self._normalize_years(years)

        if as_dataframe:
            pd, _ = self._try_import_pandas()
            if pd is not None:
                reserved = {"encoding", "nrows", "usecols"}
                conflicts = sorted(reserved.intersection(kwargs))
                if conflicts:
                    raise TypeError(
                        "load_table controls these reader arguments directly: "
                        + ", ".join(conflicts)
                    )
                read_kwargs = dict(kwargs)
                read_kwargs["encoding"] = "utf-8-sig"
                if parse_dates is True and (columns is None or GATEWAY_DATE_COLUMN in columns):
                    read_kwargs["parse_dates"] = [GATEWAY_DATE_COLUMN]
                elif parse_dates:
                    read_kwargs["parse_dates"] = parse_dates

                if selected_years is None:
                    if columns is not None:
                        read_kwargs["usecols"] = columns
                    if nrows is not None:
                        read_kwargs["nrows"] = nrows
                    return pd.read_csv(self.get_resource_path(resource_id), **read_kwargs)
                if not selected_years:
                    return pd.DataFrame(columns=columns or self.read_header())

                frames = []
                remaining = nrows
                official_columns = self.read_header(year=selected_years[0])
                for year in selected_years:
                    if remaining == 0:
                        break
                    partition_kwargs = dict(read_kwargs)
                    if columns is not None:
                        physical_columns = [
                            column for column in columns if column != SOURCE_YEAR_COLUMN
                        ]
                        if not physical_columns:
                            physical_columns = [EU_LOCAL_NUMBER_COLUMN]
                        partition_kwargs["usecols"] = physical_columns
                    if remaining is not None:
                        partition_kwargs["nrows"] = remaining
                    frame = pd.read_csv(self.get_partition_path(year), **partition_kwargs)
                    frame[SOURCE_YEAR_COLUMN] = str(year)
                    if columns is not None:
                        frame = frame.loc[:, columns]
                    frames.append(frame)
                    if remaining is not None:
                        remaining -= len(frame)
                if frames:
                    return pd.concat(frames, ignore_index=True)
                return pd.DataFrame(columns=columns or official_columns + [SOURCE_YEAR_COLUMN])

        return list(
            self.iter_rows(
                resource_id=resource_id,
                columns=columns,
                years=selected_years,
                limit=nrows,
            )
        )

    def iter_rows(
        self,
        resource_id: str = LINE_LISTING_RESOURCE_ID,
        columns: list[str] | None = None,
        years: int | str | list[int | str] | tuple[int | str, ...] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, str]]:
        self._require_tabular_resource(resource_id)
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if columns is not None:
            self.check_columns(columns)
        if limit == 0:
            return

        selected_years = self._normalize_years(years)
        if selected_years is None:
            sources: list[tuple[int | None, Path]] = [(None, self.get_resource_path(resource_id))]
        else:
            sources = [(year, self.get_partition_path(year)) for year in selected_years]

        yielded = 0
        for year, path in sources:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, restkey="_extra_fields")
                for row in reader:
                    extra_fields = row.pop("_extra_fields", None) or []
                    if any(value not in {None, ""} for value in extra_fields):
                        raise DatasetAdapterError(f"row contains extra CSV fields in {path}")
                    if year is not None:
                        row[SOURCE_YEAR_COLUMN] = str(year)
                    if columns is not None:
                        yield {column: row[column] for column in columns}
                    else:
                        yield dict(row)
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return

    def iter_batches(
        self,
        resource_id: str = LINE_LISTING_RESOURCE_ID,
        columns: list[str] | None = None,
        years: int | str | list[int | str] | tuple[int | str, ...] | None = None,
        batch_size: int = 10_000,
        limit: int | None = None,
        as_dataframe: bool = True,
    ) -> Iterator[Any]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")

        pd = None
        if as_dataframe:
            pd, _ = self._try_import_pandas()
        batch: list[dict[str, str]] = []
        for row in self.iter_rows(
            resource_id=resource_id,
            columns=columns,
            years=years,
            limit=limit,
        ):
            batch.append(row)
            if len(batch) == batch_size:
                yield pd.DataFrame(batch) if pd is not None else batch
                batch = []
        if batch:
            yield pd.DataFrame(batch) if pd is not None else batch

    def preview(self, resource_id: str = LINE_LISTING_RESOURCE_ID, n: int = 5) -> dict[str, Any]:
        self._require_tabular_resource(resource_id)
        resource = self._resource(resource_id)
        count_summary = resource.get("count_summary") or {}
        return {
            "resource_id": resource_id,
            "columns": self.read_header(resource_id),
            "shape": {
                "n_rows": count_summary.get("row_count", "unknown"),
                "n_columns": count_summary.get("column_count", "unknown"),
            },
            "preview_rows": [],
            "privacy_note": (
                "Case-level values are omitted from preview. "
                f"Use iter_rows(limit={n}) explicitly if inspection is necessary."
            ),
        }

    def validate(self, deep: bool = False) -> dict[str, list[str]]:
        passed: list[str] = []
        warnings: list[str] = []
        failures: list[str] = []

        for filename in ["resources.yaml", "dataset_graph.yaml", "adapter.py", "manifest.json"]:
            if (self.root / filename).is_file():
                passed.append(f"{filename} exists")
            else:
                failures.append(f"{filename} missing")

        result_set_ids = [resource.get("result_set_id") for resource in self._resources.values()]
        if None in result_set_ids or len(result_set_ids) != len(set(result_set_ids)):
            failures.append("resources must have unique non-empty result_set_id values")
        else:
            passed.append("resource result sets are unique")

        declared_paths = [
            path for resource in self._resources.values() for path in resource.get("paths", [])
        ]
        if len(declared_paths) != len(set(declared_paths)):
            failures.append("the same path is declared by more than one resource")
        else:
            passed.append("resource paths are unique")

        line_listing = self._resource(LINE_LISTING_RESOURCE_ID)
        requested_partitions = self.list_partitions(include_empty=True)
        equivalent_paths = {partition["raw_file"] for partition in requested_partitions}
        unpartitioned = self.manifest_doc.get("unpartitioned_official_export", {})
        if unpartitioned.get("raw_file"):
            equivalent_paths.add(unpartitioned["raw_file"])
        duplicate_declarations = sorted(equivalent_paths.intersection(declared_paths))
        if duplicate_declarations:
            failures.append(
                "equivalent exports must not be separate resources: "
                + ", ".join(duplicate_declarations)
            )
        else:
            passed.append("equivalent exports are not duplicated as resources")

        for resource_id, resource in self._resources.items():
            for relative_path in resource.get("paths", []):
                path = self.root / relative_path
                if path.is_file():
                    passed.append(f"{resource_id} path exists: {relative_path}")
                else:
                    failures.append(f"{resource_id} path missing: {relative_path}")

        try:
            observed_header = self.read_header()
            declared_columns = line_listing.get("columns") or []
            if observed_header == declared_columns:
                passed.append("canonical line-listing header matches resources.yaml")
            else:
                failures.append("canonical line-listing header differs from resources.yaml")
        except Exception as exc:  # noqa: BLE001 - validation accumulates all failures.
            failures.append(f"canonical line-listing header read failed: {exc}")

        expected_sha256 = line_listing.get("sha256")
        canonical_path = self.get_resource_path()
        if expected_sha256 and canonical_path.is_file():
            observed_sha256 = self._sha256(canonical_path)
            if observed_sha256 == expected_sha256:
                passed.append("canonical line-listing checksum matches")
            else:
                failures.append(
                    "canonical line-listing checksum mismatch: "
                    f"expected {expected_sha256}, observed {observed_sha256}"
                )

        for partition in requested_partitions:
            path = self.root / partition["raw_file"]
            if not path.is_file():
                failures.append(f"partition path missing: {partition['raw_file']}")
        if not any(failure.startswith("partition path missing") for failure in failures):
            passed.append("all manifest partition paths exist")
        if unpartitioned.get("raw_file"):
            unpartitioned_path = self.root / unpartitioned["raw_file"]
            if unpartitioned_path.is_file():
                passed.append("unpartitioned equivalent export exists")
            else:
                failures.append(
                    f"unpartitioned equivalent export missing: {unpartitioned['raw_file']}"
                )

        declared_resource_ids = set(self._resources)
        for entity in self.graph_doc.get("entities", []):
            missing = sorted(set(entity.get("resource_ids", [])) - declared_resource_ids)
            if missing:
                failures.append(
                    f"{entity.get('entity_id', '<unknown>')} graph resources missing from resources.yaml: "
                    + ", ".join(missing)
                )
        if not any("graph resources missing" in failure for failure in failures):
            passed.append("dataset graph resources are declared")

        if deep and canonical_path.is_file():
            row_count = 0
            case_ids: set[str] = set()
            source_year_mismatches = 0
            for row in self.iter_rows():
                row_count += 1
                case_ids.add(row[EU_LOCAL_NUMBER_COLUMN])
                gateway_date = row[GATEWAY_DATE_COLUMN]
                if len(gateway_date) >= 4 and gateway_date[:4] != row[SOURCE_YEAR_COLUMN]:
                    source_year_mismatches += 1
            expected_rows = int(self.manifest_doc.get("records", -1))
            if row_count == expected_rows:
                passed.append(f"deep row count matches manifest: {row_count}")
            else:
                failures.append(
                    f"deep row count mismatch: expected {expected_rows}, observed {row_count}"
                )
            if len(case_ids) == row_count:
                passed.append("deep EU Local Number uniqueness check passed")
            else:
                failures.append(
                    f"deep duplicate EU Local Number check failed: {row_count - len(case_ids)} repeats"
                )
            if source_year_mismatches == 0:
                passed.append("deep source-year provenance check passed")
            else:
                failures.append(
                    f"deep source-year provenance check found {source_year_mismatches} mismatches"
                )
        elif not deep:
            warnings.append("full row-count, uniqueness, and provenance scans were not requested")

        _, pandas_error = self._try_import_pandas()
        if pandas_error:
            warnings.append(f"pandas unavailable; stdlib CSV fallback is active: {pandas_error}")
        return {"passed": passed, "warnings": warnings, "failures": failures}

    def _resource(self, resource_id: str) -> dict[str, Any]:
        resource = self._resources.get(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"unknown resource_id: {resource_id}")
        return resource

    def _require_tabular_resource(self, resource_id: str) -> None:
        resource = self._resource(resource_id)
        if resource.get("file_format") != "csv" or resource.get("compression") != "none":
            raise UnsupportedFormatError(
                f"resource is not an uncompressed CSV table: {resource_id}"
            )

    def _normalize_year(self, year: int | str) -> int:
        try:
            normalized = int(year)
        except (TypeError, ValueError) as exc:
            raise ResourceNotFoundError(f"invalid source year bucket: {year}") from exc
        if normalized not in set(self.list_years(include_empty=True)):
            raise ResourceNotFoundError(f"unknown source year bucket: {normalized}")
        return normalized

    def _normalize_years(
        self,
        years: int | str | list[int | str] | tuple[int | str, ...] | None,
    ) -> list[int] | None:
        if years is None:
            return None
        values = [years] if isinstance(years, (int, str)) else list(years)
        normalized = [self._normalize_year(year) for year in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("source year buckets must be unique")
        return normalized

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise DatasetAdapterError(f"missing required file: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise DatasetAdapterError(f"missing required file: {path}")
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise DatasetAdapterError(f"expected a JSON object: {path}")
        return value

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
        except Exception as exc:  # noqa: BLE001 - import environments fail in several ways.
            detail = str(exc) or exc.__class__.__name__
            return None, detail
