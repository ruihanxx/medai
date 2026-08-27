from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import importlib
import io
from pathlib import Path
from typing import Iterator

import yaml


class DatasetAdapterError(Exception):
    pass


class ResourceNotFoundError(DatasetAdapterError):
    pass


class ColumnNotFoundError(DatasetAdapterError):
    pass


class UnsupportedFormatError(DatasetAdapterError):
    pass


class DatasetAdapter:
    """Standard access layer for the MIMIC-IV dataset capsule.

    The capsule combines MIMIC-IV v3.1 with the separately versioned full
    MIMIC-IV-ED v2.2 component. No official local loader was present in raw/.
    This adapter therefore uses the generated resource contract and a minimal
    CSV reader. Pandas is used when available; otherwise load_table falls back
    to list[dict].
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.resources_path = self.root / 'resources.yaml'
        self.graph_path = self.root / 'dataset_graph.yaml'
        self.resources_doc = self._read_yaml(self.resources_path)
        self.graph_doc = self._read_yaml(self.graph_path)
        self._resources = {r['resource_id']: r for r in self.resources_doc.get('resources', [])}

    def describe(self) -> dict:
        return {
            'dataset_id': self.resources_doc.get('dataset_id'),
            'dataset_name': self.resources_doc.get('dataset_name'),
            'version': self.resources_doc.get('version'),
            'components': list(self.resources_doc.get('components', [])),
            'generated_at': self.resources_doc.get('generated_at'),
            'resource_count': len(self._resources),
            'tabular_resource_count': sum(
                bool(resource.get('columns')) for resource in self._resources.values()
            ),
            'entities': len(self.graph_doc.get('entities', [])),
            'relationships': len(self.graph_doc.get('relationships', [])),
            'privacy_note': 'preview() is schema-only by default for sensitive clinical data.',
        }

    def list_resources(self) -> list[dict]:
        return list(self.resources_doc.get('resources', []))

    def get_resource_path(self, resource_id: str) -> Path:
        resource = self._resources.get(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f'unknown resource_id: {resource_id}')
        paths = resource.get('paths') or []
        if len(paths) != 1:
            raise ResourceNotFoundError(f'resource {resource_id} does not resolve to exactly one path')
        return self.root / paths[0]

    def read_header(self, resource_id: str) -> list[str]:
        path = self.get_resource_path(resource_id)
        resource = self._resources[resource_id]
        if resource.get('file_format') != 'csv' or resource.get('compression') != 'gzip':
            raise UnsupportedFormatError(f'{resource_id} is not a gzip CSV resource')
        with gzip.open(path, 'rt', newline='') as f:
            return next(csv.reader(f))

    def check_columns(self, resource_id: str, columns: list[str]) -> None:
        header = self.read_header(resource_id)
        missing = [c for c in columns if c not in header]
        if missing:
            raise ColumnNotFoundError(f'resource {resource_id} missing requested columns: {missing}')

    def load_table(
        self,
        resource_id: str,
        columns: list[str] | None = None,
        parse_dates: bool | list[str] = False,
        nrows: int | None = None,
        as_dataframe: bool = True,
        **kwargs,
    ):
        path = self.get_resource_path(resource_id)
        resource = self._resources[resource_id]
        if resource.get('file_format') != 'csv' or resource.get('compression') != 'gzip':
            raise UnsupportedFormatError(f'{resource_id} is not a supported tabular resource')
        if columns is not None:
            self.check_columns(resource_id, columns)
        if as_dataframe:
            pd, error = self._try_import_pandas()
            if pd is not None:
                read_kwargs = dict(kwargs)
                read_kwargs.setdefault('compression', 'gzip')
                if columns is not None:
                    read_kwargs['usecols'] = columns
                if nrows is not None:
                    read_kwargs['nrows'] = nrows
                if parse_dates:
                    read_kwargs['parse_dates'] = parse_dates
                return pd.read_csv(path, **read_kwargs)
        return list(self.iter_rows(resource_id, columns=columns, limit=nrows))

    def iter_rows(
        self,
        resource_id: str,
        columns: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict]:
        path = self.get_resource_path(resource_id)
        if columns is not None:
            self.check_columns(resource_id, columns)
        with gzip.open(path, 'rt', newline='') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit is not None and i >= limit:
                    break
                if columns is not None:
                    yield {col: row.get(col) for col in columns}
                else:
                    yield row

    def iter_batches(
        self,
        resource_id: str,
        columns: list[str] | None = None,
        batch_size: int = 10_000,
        limit: int | None = None,
        parse_dates: bool | list[str] = False,
        as_dataframe: bool = True,
        **kwargs,
    ) -> Iterator:
        """Yield bounded batches without materializing the complete resource.

        With pandas available and ``as_dataframe=True``, batches are DataFrames.
        Otherwise, each batch is a list of row dictionaries from ``iter_rows``.
        ``limit`` bounds source rows read before downstream filtering; callers
        remain responsible for paper-specific per-batch preprocessing.
        """
        if batch_size <= 0:
            raise ValueError('batch_size must be greater than zero')
        if limit is not None and limit < 0:
            raise ValueError('limit must be non-negative')

        path = self.get_resource_path(resource_id)
        resource = self._resources[resource_id]
        if resource.get('file_format') != 'csv' or resource.get('compression') != 'gzip':
            raise UnsupportedFormatError(f'{resource_id} is not a supported tabular resource')
        if columns is not None:
            self.check_columns(resource_id, columns)
        if limit == 0:
            return

        if as_dataframe:
            pd, _ = self._try_import_pandas()
            if pd is not None:
                reserved = {'chunksize', 'compression', 'iterator', 'nrows', 'usecols'}
                conflicts = sorted(reserved.intersection(kwargs))
                if conflicts:
                    raise TypeError(
                        'iter_batches controls these reader arguments directly: '
                        + ', '.join(conflicts)
                    )
                read_kwargs = dict(kwargs)
                read_kwargs['compression'] = 'gzip'
                read_kwargs['chunksize'] = batch_size
                if columns is not None:
                    read_kwargs['usecols'] = columns
                if limit is not None:
                    read_kwargs['nrows'] = limit
                if parse_dates:
                    read_kwargs['parse_dates'] = parse_dates
                yield from pd.read_csv(path, **read_kwargs)
                return

        batch: list[dict] = []
        for row in self.iter_rows(resource_id, columns=columns, limit=limit):
            batch.append(row)
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def preview(self, resource_id: str, n: int = 5) -> dict:
        header = self.read_header(resource_id)
        resource = self._resources[resource_id]
        count_summary = resource.get('count_summary') or {}
        return {
            'resource_id': resource_id,
            'columns': header,
            'shape': {
                'n_rows': count_summary.get('row_count', 'unknown'),
                'n_columns': count_summary.get('column_count', len(header)),
            },
            'preview_rows': [],
            'privacy_note': f'Row-level preview suppressed for sensitive clinical data. Use iter_batches(..., limit={n}) or iter_rows(..., limit={n}) explicitly if local inspection is necessary.',
        }

    def validate(self, deep: bool = False) -> dict:
        passed: list[str] = []
        warnings: list[str] = []
        failures: list[str] = []
        for filename in ['resources.yaml', 'dataset_graph.yaml', 'adapter.py', 'validation.py', 'unresolved.md']:
            if (self.root / filename).exists():
                passed.append(f'{filename} exists')
            else:
                failures.append(f'{filename} missing')
        for resource_id, resource in self._resources.items():
            for rel in resource.get('paths') or []:
                if (self.root / rel).exists():
                    passed.append(f'{resource_id} path exists')
                else:
                    failures.append(f'{resource_id} path missing: {rel}')
            if resource.get('file_format') == 'csv' and resource.get('compression') == 'gzip':
                try:
                    header = self.read_header(resource_id)
                    passed.append(f'{resource_id} header readable')
                    declared = resource.get('columns') or []
                    missing = [c for c in declared if c not in header]
                    if missing:
                        failures.append(f'{resource_id} declared columns missing from raw header: {missing}')
                    else:
                        passed.append(f'{resource_id} declared columns match header')
                except Exception as exc:  # noqa: BLE001 - validation reports all resource errors.
                    failures.append(f'{resource_id} header read failed: {exc}')
            expected_sha256 = resource.get('sha256')
            if expected_sha256:
                paths = resource.get('paths') or []
                if len(paths) != 1:
                    failures.append(f'{resource_id} checksum requires exactly one path')
                else:
                    path = self.root / paths[0]
                    if path.exists():
                        observed_sha256 = self._sha256(path)
                        if observed_sha256 == expected_sha256:
                            passed.append(f'{resource_id} checksum matches')
                        else:
                            failures.append(
                                f'{resource_id} checksum mismatch: '
                                f'expected {expected_sha256}, observed {observed_sha256}'
                            )
        declared_resource_ids = set(self._resources)
        for entity in self.graph_doc.get('entities', []):
            missing = sorted(set(entity.get('resource_ids') or []) - declared_resource_ids)
            if missing:
                failures.append(
                    f"{entity.get('entity_id', '<unknown>')} graph resources missing from resources.yaml: "
                    + ', '.join(missing)
                )
        if not any('graph resources missing' in failure for failure in failures):
            passed.append('dataset graph resources are declared')
        if deep:
            warnings.append('deep validation is intentionally lightweight; full-row scans are not performed by default')
        _, pandas_error = self._try_import_pandas()
        if pandas_error:
            warnings.append(f'pandas unavailable; stdlib CSV fallback is active: {pandas_error}')
        return {'passed': passed, 'warnings': warnings, 'failures': failures}

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        if not path.exists():
            raise DatasetAdapterError(f'missing required file: {path}')
        with path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _try_import_pandas():
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                return importlib.import_module('pandas'), None
        except Exception as exc:  # noqa: BLE001 - import environment can fail in several ways.
            detail = str(exc) or exc.__class__.__name__
            return None, detail
