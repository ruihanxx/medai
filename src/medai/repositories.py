from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from medai.models import (
    PaperRepositories,
    PaperRepository,
    RepositoryCandidate,
)

IGNORED_REPOSITORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "runs",
    "replicate",
}


def repository_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_REPOSITORY_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            digest.update(f"L\0{relative.as_posix()}\0{os.readlink(path)}\0".encode())
        elif path.is_file():
            digest.update(f"F\0{relative.as_posix()}\0".encode())
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def repository_tree_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_REPOSITORY_NAMES for part in relative.parts):
            continue
        relative_text = relative.as_posix()
        if path.is_symlink():
            manifest[relative_text] = f"link:{os.readlink(path)}"
        elif path.is_file():
            manifest[relative_text] = f"file:{_sha256_file(path)}"
    return manifest


def validate_repository_snapshots(inventory: PaperRepositories, run_root: Path) -> None:
    for repository in inventory.available:
        assert repository.snapshot_path is not None
        snapshot = run_root / repository.snapshot_path
        if not snapshot.is_dir():
            raise RuntimeError(f"Repository snapshot is missing: {snapshot}")
        actual = repository_tree_sha256(snapshot)
        if actual != repository.tree_sha256:
            raise RuntimeError(f"Repository snapshot changed after preflight: {snapshot}")


def normalize_public_git_url(
    url: str,
    *,
    resolve_host: bool = True,
) -> tuple[str, str | None]:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Repository URLs must be public HTTPS URLs without credentials")
    if resolve_host:
        _require_public_hostname(parsed.hostname)
    else:
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("Repository hostname must not be a private address")
    path = parsed.path.rstrip("/")
    revision: str | None = None
    parts = [part for part in path.split("/") if part]
    hostname = parsed.hostname.casefold()
    if hostname == "github.com" and len(parts) >= 2:
        if len(parts) >= 4 and parts[2] in {"tree", "commit"}:
            revision = parts[3]
        path = "/" + "/".join(parts[:2])
    elif hostname == "bitbucket.org" and len(parts) >= 2:
        if len(parts) >= 4 and parts[2] == "src":
            revision = parts[3]
        path = "/" + "/".join(parts[:2])
    elif "gitlab" in hostname and "/-/" in path:
        project_path, suffix = path.split("/-/", 1)
        suffix_parts = suffix.split("/")
        if len(suffix_parts) >= 2 and suffix_parts[0] in {"tree", "commit"}:
            revision = suffix_parts[1]
        path = project_path
    elif not path.endswith(".git"):
        raise ValueError(
            "Non-forge repository URLs must use an explicit .git clone URL"
        )
    if not path.endswith(".git"):
        path += ".git"
    return urlunsplit(("https", parsed.netloc, path, "", "")), revision


def acquire_repositories(
    *,
    candidates: list[RepositoryCandidate],
    local_repository: Path | None,
    run_root: Path,
) -> PaperRepositories:
    repositories_root = run_root / "preflight" / "repositories"
    repositories_root.mkdir(parents=True, exist_ok=True)
    repositories: list[PaperRepository] = []
    seen_clone_urls: dict[tuple[str, str | None], PaperRepository] = {}
    seen_tree_hashes: dict[str, PaperRepository] = {}

    for candidate in candidates:
        source_location = candidate.url
        try:
            clone_url, url_revision = normalize_public_git_url(candidate.url)
        except (OSError, ValueError) as exc:
            repositories.append(
                _unavailable_repository(
                    len(repositories) + 1,
                    source_kind="paper_url",
                    source_location=source_location,
                    disclosed_url=candidate.url,
                    clone_url=None,
                    revision=candidate.revision,
                    evidence=[candidate.evidence],
                    error=str(exc),
                )
            )
            continue
        revision = url_revision
        clone_identity = (clone_url, revision)
        existing = seen_clone_urls.get(clone_identity)
        if existing is not None:
            existing.source_kinds.append("paper_url")
            existing.source_locations.append(source_location)
            existing.paper_evidence.append(candidate.evidence)
            continue
        repository_id = f"R{len(repositories) + 1:03d}"
        snapshot = repositories_root / repository_id
        try:
            commit_sha, incomplete = _clone_repository(clone_url, revision, snapshot)
            tree_sha256 = repository_tree_sha256(snapshot)
            duplicate = seen_tree_hashes.get(tree_sha256)
            if duplicate is not None:
                shutil.rmtree(snapshot)
                duplicate.source_kinds.append("paper_url")
                duplicate.source_locations.append(source_location)
                duplicate.paper_evidence.append(candidate.evidence)
                seen_clone_urls[clone_identity] = duplicate
                continue
            repository = PaperRepository(
                id=repository_id,
                source_kinds=["paper_url"],
                source_locations=[source_location],
                paper_evidence=[candidate.evidence],
                disclosed_url=candidate.url,
                clone_url=clone_url,
                revision=revision,
                status="available",
                commit_sha=commit_sha,
                tree_sha256=tree_sha256,
                snapshot_path=snapshot.relative_to(run_root).as_posix(),
                acquired_at=_now(),
                error=None,
                incomplete=incomplete,
            )
            repositories.append(repository)
            seen_clone_urls[clone_identity] = repository
            seen_tree_hashes[tree_sha256] = repository
        except Exception as exc:
            if snapshot.exists():
                shutil.rmtree(snapshot)
            repositories.append(
                _unavailable_repository(
                    len(repositories) + 1,
                    source_kind="paper_url",
                    source_location=source_location,
                    disclosed_url=candidate.url,
                    clone_url=clone_url,
                    revision=revision,
                    evidence=[candidate.evidence],
                    error=_sanitized_error(exc),
                )
            )

    if local_repository is not None:
        repository_id = f"R{len(repositories) + 1:03d}"
        snapshot = repositories_root / repository_id
        try:
            commit_sha, incomplete = _snapshot_local_repository(local_repository, snapshot)
            tree_sha256 = repository_tree_sha256(snapshot)
            duplicate = seen_tree_hashes.get(tree_sha256)
            if duplicate is not None:
                shutil.rmtree(snapshot)
                duplicate.source_kinds.append("local")
                duplicate.source_locations.append(str(local_repository))
            else:
                repositories.append(
                    PaperRepository(
                        id=repository_id,
                        source_kinds=["local"],
                        source_locations=[str(local_repository)],
                        paper_evidence=[],
                        disclosed_url=None,
                        clone_url=None,
                        revision=None,
                        status="available",
                        commit_sha=commit_sha,
                        tree_sha256=tree_sha256,
                        snapshot_path=snapshot.relative_to(run_root).as_posix(),
                        acquired_at=_now(),
                        error=None,
                        incomplete=incomplete,
                    )
                )
        except Exception as exc:
            if snapshot.exists():
                shutil.rmtree(snapshot)
            repositories.append(
                _unavailable_repository(
                    len(repositories) + 1,
                    source_kind="local",
                    source_location=str(local_repository),
                    disclosed_url=None,
                    clone_url=None,
                    revision=None,
                    evidence=[],
                    error=_sanitized_error(exc),
                )
            )

    return PaperRepositories(repositories=repositories)


def _require_public_hostname(hostname: str) -> None:
    if hostname.casefold() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Repository hostname must be public")
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Repository hostname could not be resolved: {hostname}") from exc
    if not addresses:
        raise ValueError(f"Repository hostname could not be resolved: {hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Repository hostname must not resolve to a private address")


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return environment


def _run_git(arguments: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=_git_environment(),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError(f"git {' '.join(arguments[:2])} failed: {detail}")
    return result.stdout.strip()


def _clone_repository(
    clone_url: str,
    revision: str | None,
    destination: Path,
) -> tuple[str, list[str]]:
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists() or destination.exists():
        raise RuntimeError(f"Repository snapshot target already exists: {destination}")
    arguments = [
        "-c",
        "core.hooksPath=/dev/null",
        "clone",
        "--filter=blob:none",
        "--no-tags",
    ]
    if revision is None:
        arguments.extend(["--depth", "1"])
    arguments.extend([clone_url, str(temporary)])
    try:
        _run_git(arguments)
        if revision is not None:
            _run_git(["fetch", "--depth", "1", "origin", revision], cwd=temporary)
            _run_git(["checkout", "--detach", "FETCH_HEAD"], cwd=temporary)
        commit_sha = _run_git(["rev-parse", "HEAD"], cwd=temporary)
        incomplete = _acquire_submodules(temporary, clone_url)
        incomplete.extend(_find_lfs_pointers(temporary))
        _remove_git_metadata(temporary)
        _validate_snapshot_links(temporary)
        temporary.replace(destination)
        return commit_sha, incomplete
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _acquire_submodules(root: Path, parent_url: str) -> list[str]:
    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file():
        return []
    try:
        paths_output = _run_git(
            ["config", "-f", str(gitmodules), "--get-regexp", r"^submodule\..*\.path$"],
            cwd=root,
        )
        urls_output = _run_git(
            ["config", "-f", str(gitmodules), "--get-regexp", r"^submodule\..*\.url$"],
            cwd=root,
        )
    except RuntimeError as exc:
        return [f"submodule metadata unavailable: {_sanitized_error(exc)}"]
    paths = {
        line.split(maxsplit=1)[0][10:-5]: line.split(maxsplit=1)[1]
        for line in paths_output.splitlines()
    }
    urls = {
        line.split(maxsplit=1)[0][10:-4]: line.split(maxsplit=1)[1]
        for line in urls_output.splitlines()
    }
    incomplete: list[str] = []
    for name, relative_path in paths.items():
        raw_url = urls.get(name)
        if raw_url is None:
            incomplete.append(f"submodule {name} has no URL")
            continue
        submodule_path = (root / relative_path).resolve()
        if not submodule_path.is_relative_to(root.resolve()):
            incomplete.append(f"submodule {name} has an unsafe path")
            continue
        resolved_url = (
            urljoin(parent_url.rstrip("/") + "/", raw_url)
            if raw_url.startswith(("./", "../"))
            else raw_url
        )
        try:
            clone_url, _ = normalize_public_git_url(resolved_url)
            status = _run_git(["ls-tree", "HEAD", relative_path], cwd=root)
            commit = status.split()[2]
            _clone_repository(clone_url, commit, submodule_path)
        except Exception as exc:
            incomplete.append(f"submodule {name} unavailable: {_sanitized_error(exc)}")
    return incomplete


def _snapshot_local_repository(source: Path, destination: Path) -> tuple[str | None, list[str]]:
    if destination.exists():
        raise RuntimeError(f"Repository snapshot target already exists: {destination}")
    commit_sha: str | None = None
    incomplete: list[str] = []
    try:
        commit_sha = _run_git(["rev-parse", "HEAD"], cwd=source)
        if _run_git(["status", "--porcelain"], cwd=source):
            incomplete.append("local repository contains uncommitted changes")
    except RuntimeError:
        incomplete.append("local source is not a Git working tree")
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(*sorted(IGNORED_REPOSITORY_NAMES)),
    )
    _validate_snapshot_links(destination)
    incomplete.extend(_find_lfs_pointers(destination))
    return commit_sha, incomplete


def _validate_snapshot_links(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = (path.parent / os.readlink(path)).resolve()
        if not target.is_relative_to(resolved_root):
            raise RuntimeError(f"Repository contains an unsafe symlink: {path.relative_to(root)}")


def _find_lfs_pointers(root: Path) -> list[str]:
    pointers: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size > 4096:
            continue
        try:
            first_line = path.open("r", encoding="utf-8").readline().strip()
        except (OSError, UnicodeDecodeError):
            continue
        if first_line == "version https://git-lfs.github.com/spec/v1":
            pointers.append(f"Git LFS payload not downloaded: {path.relative_to(root)}")
    return pointers


def _remove_git_metadata(root: Path) -> None:
    for path in sorted(root.rglob(".git"), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _unavailable_repository(
    index: int,
    *,
    source_kind: str,
    source_location: str,
    disclosed_url: str | None,
    clone_url: str | None,
    revision: str | None,
    evidence: list[str],
    error: str,
) -> PaperRepository:
    return PaperRepository(
        id=f"R{index:03d}",
        source_kinds=[source_kind],
        source_locations=[source_location],
        paper_evidence=evidence,
        disclosed_url=disclosed_url,
        clone_url=clone_url,
        revision=revision,
        status="unavailable",
        commit_sha=None,
        tree_sha256=None,
        snapshot_path=None,
        acquired_at=None,
        error=error,
        incomplete=[],
    )


def _sanitized_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[-2000:] or type(exc).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
