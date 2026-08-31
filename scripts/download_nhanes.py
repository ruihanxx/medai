#!/usr/bin/env python3
"""Download every public-use Continuous NHANES XPT file in a year range."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import ssl
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

COMPONENTS = ("Demographics", "Dietary", "Examination", "Laboratory", "Questionnaire")
CATALOG_URL = (
    "https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx"
    "?Component={component}&CycleBeginYear="
)
LANDING_URL = "https://wwwn.cdc.gov/nchs/nhanes/Default.aspx"
USER_AGENT = "medai-nhanes-downloader/1.0"
XPT_HEADER_PREFIX = b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"
LARGE_FILE_THRESHOLD = 1024**3
RANGE_CHUNK_BYTES = 4 * 1024**2
YEAR_RANGE_RE = re.compile(r"^(\d{4})-(\d{4})\b")
SIZE_RE = re.compile(r"\[XPT\s*-\s*([\d.,]+)\s*(KB|MB|GB)\]", re.IGNORECASE)
CURRENT_CYCLE_RE = re.compile(r"default\.aspx\?Cycle=(\d{4}-\d{4})", re.IGNORECASE)


class CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, list[tuple[str, str]]]] = []
        self._in_row = False
        self._row_text: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._row_text = []
            self._links = []
        elif tag == "a" and self._in_row:
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._row_text.append(data)
        if self._href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self._links.append((self._href, " ".join("".join(self._link_text).split())))
            self._href = None
            self._link_text = []
        elif tag == "tr" and self._in_row:
            text = " ".join("".join(self._row_text).split())
            self.rows.append((text, self._links))
            self._in_row = False


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response:
        return response.read().decode("utf-8", "replace")


def advertised_bytes(text: str) -> int | None:
    match = SIZE_RE.search(text)
    if match is None:
        return None
    multiplier = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[match.group(2).upper()]
    return round(float(match.group(1).replace(",", "")) * multiplier)


def discover_files(start_year: int, end_year: int) -> tuple[list[dict[str, object]], list[str]]:
    files_by_url: dict[str, dict[str, object]] = {}
    for component in COMPONENTS:
        url = CATALOG_URL.format(component=component)
        parser = CatalogParser()
        parser.feed(fetch_text(url))
        for row_text, links in parser.rows:
            cycle_match = YEAR_RANGE_RE.match(row_text)
            if cycle_match is None:
                continue
            cycle_start, cycle_end = map(int, cycle_match.groups())
            if cycle_end < start_year or cycle_start > end_year:
                continue
            cycle = cycle_match.group(0)
            for href, link_text in links:
                source_url = urljoin("https://wwwn.cdc.gov", href)
                parsed = urlparse(source_url)
                if not parsed.path.lower().endswith(".xpt"):
                    continue
                filename = Path(parsed.path).name
                relative_path = Path("raw", cycle, component.lower(), filename).as_posix()
                if source_url in files_by_url:
                    raise RuntimeError(f"Duplicate official source URL: {source_url}")
                files_by_url[source_url] = {
                    "component": component.lower(),
                    "cycle": cycle,
                    "filename": filename,
                    "source_url": source_url,
                    "relative_path": relative_path,
                    "advertised_size": SIZE_RE.search(link_text).group(0)[1:-1]
                    if SIZE_RE.search(link_text)
                    else None,
                    "advertised_bytes": advertised_bytes(link_text),
                    "status": "pending",
                }

    files = sorted(
        files_by_url.values(),
        key=lambda item: (str(item["cycle"]), str(item["component"]), str(item["filename"])),
    )
    paths = [str(item["relative_path"]) for item in files]
    if len(paths) != len(set(paths)):
        raise RuntimeError("Official catalog produced duplicate destination paths")

    landing_html = fetch_text(LANDING_URL)
    current_cycles = sorted(set(CURRENT_CYCLE_RE.findall(landing_html)))
    file_cycles = {str(item["cycle"]) for item in files}
    listed_without_xpt = [
        cycle
        for cycle in current_cycles
        if int(cycle.split("-")[1]) >= start_year
        and int(cycle.split("-")[0]) <= end_year
        and cycle not in file_cycles
    ]
    return files, listed_without_xpt


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_xpt(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= len(XPT_HEADER_PREFIX):
        return False
    with path.open("rb") as stream:
        return stream.read(len(XPT_HEADER_PREFIX)) == XPT_HEADER_PREFIX


def download_range_part(
    source_url: str,
    part_path: Path,
    start: int,
    end: int,
    ca_options: list[str],
) -> None:
    expected_bytes = end - start + 1
    if part_path.is_file() and part_path.stat().st_size == expected_bytes:
        return
    if part_path.exists():
        part_path.unlink()
    temporary = part_path.with_suffix(".partial")
    if temporary.exists():
        temporary.unlink()
    command = [
        "curl",
        *ca_options,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "12",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--range",
        f"{start}-{end}",
        "--output",
        str(temporary),
        "--write-out",
        "%{http_code}",
        "--user-agent",
        USER_AGENT,
        source_url,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        error = completed.stderr.strip() or f"curl exited {completed.returncode}"
        raise RuntimeError(f"range {start}-{end}: {error}")
    if completed.stdout.strip() != "206":
        raise RuntimeError(f"range {start}-{end}: expected HTTP 206, got {completed.stdout!r}")
    actual_bytes = temporary.stat().st_size if temporary.exists() else 0
    if actual_bytes != expected_bytes:
        raise RuntimeError(
            f"range {start}-{end}: expected {expected_bytes} bytes, got {actual_bytes}"
        )
    temporary.replace(part_path)


def download_segmented(
    source_url: str,
    destination: Path,
    ca_options: list[str],
    range_jobs: int,
) -> None:
    head_command = [
        "curl",
        *ca_options,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--head",
        "--user-agent",
        USER_AGENT,
        source_url,
    ]
    completed = subprocess.run(head_command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        error = completed.stderr.strip() or f"curl exited {completed.returncode}"
        raise RuntimeError(f"could not read large-file headers: {error}")
    lengths = re.findall(r"^content-length:\s*(\d+)\s*$", completed.stdout, re.MULTILINE | re.I)
    if not lengths:
        raise RuntimeError("large-file response did not provide Content-Length")
    total_bytes = int(lengths[-1])
    if total_bytes <= LARGE_FILE_THRESHOLD:
        raise RuntimeError(f"unexpected large-file length: {total_bytes}")

    parts_dir = destination.with_name(f".{destination.name}.parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges = []
    start = 0
    while start < total_bytes:
        end = min(start + RANGE_CHUNK_BYTES - 1, total_bytes - 1)
        part_path = parts_dir / f"{start:012d}-{end:012d}.part"
        ranges.append((part_path, start, end))
        start = end + 1

    with ThreadPoolExecutor(max_workers=range_jobs) as executor:
        futures = [
            executor.submit(download_range_part, source_url, part_path, start, end, ca_options)
            for part_path, start, end in ranges
        ]
        for future in as_completed(futures):
            future.result()

    staged = destination.with_name(f"{destination.name}.assembled")
    with staged.open("wb") as output:
        for part_path, _, _ in ranges:
            with part_path.open("rb") as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    if staged.stat().st_size != total_bytes or not valid_xpt(staged):
        raise RuntimeError("assembled large file failed length or SAS XPORT validation")
    staged.replace(destination)
    for part_path, _, _ in ranges:
        part_path.unlink()
    parts_dir.rmdir()


def download_file(
    item: dict[str, object],
    output_dir: Path,
    prior: dict[str, object] | None,
    large_file_jobs: int,
) -> dict[str, object]:
    destination = output_dir / str(item["relative_path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if prior and prior.get("status") == "complete" and valid_xpt(destination):
        size_bytes = destination.stat().st_size
        if size_bytes == prior.get("size_bytes"):
            checksum = sha256_file(destination)
            if checksum == prior.get("sha256"):
                item.update(status="complete", size_bytes=size_bytes, sha256=checksum)
                return item

    partial = destination.with_name(f"{destination.name}.part")
    ca_file = ssl.get_default_verify_paths().cafile
    ca_options = ["--cacert", ca_file] if ca_file and Path(ca_file).is_file() else []
    if int(item.get("advertised_bytes") or 0) > LARGE_FILE_THRESHOLD:
        if partial.exists():
            partial.unlink()
        download_segmented(str(item["source_url"]), destination, ca_options, large_file_jobs)
        size_bytes = destination.stat().st_size
        checksum = sha256_file(destination)
        item.update(status="complete", size_bytes=size_bytes, sha256=checksum)
        return item

    command = [
        "curl",
        *ca_options,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "12",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--continue-at",
        "-",
        "--output",
        str(partial),
        "--user-agent",
        USER_AGENT,
        str(item["source_url"]),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode == 33 and partial.exists():
        partial.unlink()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        error = completed.stderr.strip() or f"curl exited {completed.returncode}"
        raise RuntimeError(error)
    if not valid_xpt(partial):
        raise RuntimeError("downloaded response is not a valid SAS XPORT file")
    partial.replace(destination)
    size_bytes = destination.stat().st_size
    checksum = sha256_file(destination)
    item.update(status="complete", size_bytes=size_bytes, sha256=checksum)
    return item


def write_manifest(
    path: Path,
    files: list[dict[str, object]],
    start_year: int,
    end_year: int,
    listed_without_xpt: list[str],
) -> None:
    complete_count = sum(item.get("status") == "complete" for item in files)
    failed_count = sum(item.get("status") == "failed" for item in files)
    manifest = {
        "schema_version": 1,
        "dataset": "Continuous NHANES public-use data",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_year_range": f"{start_year}-{end_year}",
        "official_landing_url": LANDING_URL,
        "official_catalog_urls": [CATALOG_URL.format(component=value) for value in COMPONENTS],
        "components": [value.lower() for value in COMPONENTS],
        "cycles_with_public_xpt": sorted({str(item["cycle"]) for item in files}),
        "listed_cycles_without_public_xpt": listed_without_xpt,
        "file_count": len(files),
        "complete_count": complete_count,
        "failed_count": failed_count,
        "complete": complete_count == len(files) and failed_count == 0,
        "files": files,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=1999)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument(
        "--output",
        type=Path,
        default=repository_root / "resources" / "datasets" / "NHANES",
    )
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument(
        "--large-file-jobs",
        type=int,
        default=64,
        help="Concurrent HTTP ranges per file larger than 1 GiB",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Refresh the catalog manifest without downloading files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start_year > args.end_year:
        raise SystemExit("--start-year must not be greater than --end-year")
    if args.jobs < 1:
        raise SystemExit("--jobs must be at least 1")
    if args.large_file_jobs < 1:
        raise SystemExit("--large-file-jobs must be at least 1")
    if not args.list_only and shutil.which("curl") is None:
        raise SystemExit("curl is required for resumable downloads")

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    prior_by_url: dict[str, dict[str, object]] = {}
    if manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prior_by_url = {
            str(item["source_url"]): item
            for item in prior_manifest.get("files", [])
            if isinstance(item, dict) and "source_url" in item
        }

    print("Reading the five official CDC NHANES component catalogs...", flush=True)
    files, listed_without_xpt = discover_files(args.start_year, args.end_year)
    for item in files:
        prior = prior_by_url.get(str(item["source_url"]))
        if prior and prior.get("relative_path") == item["relative_path"]:
            for key in ("status", "size_bytes", "sha256", "error"):
                if key in prior:
                    item[key] = prior[key]
    write_manifest(manifest_path, files, args.start_year, args.end_year, listed_without_xpt)

    advertised_total = sum(int(item.get("advertised_bytes") or 0) for item in files)
    print(
        f"Discovered {len(files)} public XPT files "
        f"(~{advertised_total / 1024**3:.1f} GiB advertised).",
        flush=True,
    )
    if listed_without_xpt:
        print(
            "Officially listed cycles with no public XPT files: "
            + ", ".join(listed_without_xpt),
            flush=True,
        )
    if args.list_only:
        print(f"Catalog manifest written to {manifest_path}", flush=True)
        return 0

    ordered = sorted(files, key=lambda item: int(item.get("advertised_bytes") or 0), reverse=True)
    file_index = {str(item["source_url"]): item for item in files}
    failures = 0
    completed_count = 0
    print(f"Downloading with {args.jobs} concurrent jobs into {output_dir}...", flush=True)
    print_lock = Lock()
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                download_file,
                dict(item),
                output_dir,
                prior_by_url.get(str(item["source_url"])),
                args.large_file_jobs,
            ): item
            for item in ordered
        }
        for future in as_completed(futures):
            source = futures[future]
            completed_count += 1
            try:
                result = future.result()
                file_index[str(result["source_url"])].update(result)
                message = f"[{completed_count}/{len(files)}] complete {result['relative_path']}"
            except Exception as exc:
                failures += 1
                source.update(status="failed", error=str(exc))
                message = f"[{completed_count}/{len(files)}] FAILED {source['relative_path']}: {exc}"
            with print_lock:
                print(message, flush=True)
            if completed_count % 20 == 0 or failures:
                write_manifest(
                    manifest_path,
                    files,
                    args.start_year,
                    args.end_year,
                    listed_without_xpt,
                )

    write_manifest(manifest_path, files, args.start_year, args.end_year, listed_without_xpt)
    checksum_path = output_dir / "SHA256SUMS"
    checksum_lines = [
        f"{item['sha256']}  {item['relative_path']}"
        for item in files
        if item.get("status") == "complete" and item.get("sha256")
    ]
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    if failures:
        print(f"{failures} files failed; rerun the same command to resume.", file=sys.stderr)
        return 1
    print(f"Downloaded and verified all {len(files)} files. Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
