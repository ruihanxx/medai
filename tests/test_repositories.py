from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from medai.config import RunConfig
from medai.data_availability import sha256_file
from medai.models import PaperRepoAmbiguity, RepositoryCandidate
from medai.pipeline_state import PipelineState
from medai.repositories import (
    _clone_repository,
    acquire_repositories,
    normalize_public_git_url,
    validate_repository_snapshots,
)
from medai.workflow import codegen_route, preflight_node


def test_normalize_public_git_url_rejects_credentials_and_normalizes_forge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("medai.repositories._require_public_hostname", lambda hostname: None)

    assert normalize_public_git_url("https://github.com/org/project/tree/v1") == (
        "https://github.com/org/project.git",
        "v1",
    )
    with pytest.raises(ValueError, match="without credentials"):
        normalize_public_git_url("https://token@github.com/org/project")
    with pytest.raises(ValueError, match="explicit .git"):
        normalize_public_git_url("https://code.example.org/org/project")
    with pytest.raises(ValueError, match="private"):
        normalize_public_git_url("https://127.0.0.1/org/project.git", resolve_host=False)


def test_clone_pins_commit_and_removes_git_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (source / "method.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "method.py"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "initial"], check=True)
    expected = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    snapshot = tmp_path / "snapshot"
    commit, incomplete = _clone_repository(str(source), expected, snapshot)

    assert commit == expected
    assert incomplete == []
    assert not (snapshot / ".git").exists()


def test_acquisition_deduplicates_local_snapshot_and_records_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    local = tmp_path / "local"
    local.mkdir()
    (local / "method.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "medai.repositories.normalize_public_git_url",
        lambda url: (url + ".git", None),
    )

    def fake_clone(url: str, revision: str | None, destination: Path):
        if "broken" in url:
            raise RuntimeError("network unavailable")
        destination.mkdir(parents=True)
        (destination / "method.py").write_text("VALUE = 1\n", encoding="utf-8")
        return "a" * 40, []

    monkeypatch.setattr("medai.repositories._clone_repository", fake_clone)
    inventory = acquire_repositories(
        candidates=[
            RepositoryCandidate(
                url="https://code.example/official",
                evidence="Code is available at the disclosed URL.",
                revision=None,
            ),
            RepositoryCandidate(
                url="https://code.example/broken",
                evidence="A second repository is disclosed.",
                revision=None,
            ),
        ],
        local_repository=local,
        run_root=run_root,
    )

    assert [repository.status for repository in inventory.repositories] == [
        "available",
        "unavailable",
    ]
    assert inventory.repositories[0].source_kinds == ["paper_url", "local"]
    assert "network unavailable" in str(inventory.repositories[1].error)
    validate_repository_snapshots(inventory, run_root)

    snapshot = run_root / str(inventory.repositories[0].snapshot_path)
    (snapshot / "method.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after preflight"):
        validate_repository_snapshots(inventory, run_root)


def test_codegen_route_runs_calibration_only_for_available_repository(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"paper")
    output = tmp_path / "run"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    inventory_path = output / "preflight" / "paper_repositories.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text('{"version":1,"repositories":[]}\n', encoding="utf-8")
    state = {"config": config, "repository_inventory_path": str(inventory_path)}
    assert codegen_route(state) == "audit_agent"  # type: ignore[arg-type]

    source = tmp_path / "local"
    source.mkdir()
    (source / "method.py").write_text("VALUE = 1\n", encoding="utf-8")
    inventory = acquire_repositories(
        candidates=[],
        local_repository=source,
        run_root=output,
    )
    inventory_path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
    assert codegen_route(state) == "repo_calibration_agent"  # type: ignore[arg-type]


def test_preflight_resume_reuses_frozen_repository_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"paper")
    output = tmp_path / "run"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )
    paper_markdown = output / "preprocessing" / "paper.md"
    paper_markdown.parent.mkdir(parents=True)
    paper_markdown.write_text("paper\n", encoding="utf-8")
    artifacts = {
        output / "preflight" / "resources.json": '{"gpus":[]}\n',
        output / "preflight" / "repository_candidates.json": (
            '{"repositories":[]}\n'
        ),
        output / "preflight" / "paper_repositories.json": (
            '{"version":1,"repositories":[]}\n'
        ),
        output / "preflight" / "repository_discovery_transcript.jsonl": "{}\n",
        output / "system_maintenance" / "dataset" / "patch.json": "[]\n",
        output / "system_maintenance" / "skills" / "corrections.json": "[]\n",
    }
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    pipeline = PipelineState.create(output, {"provider": "codex"})
    pipeline.start_stage("preflight")
    inventory_path = output / "preflight" / "paper_repositories.json"
    pipeline.update_stage_checkpoints(
        "preflight",
        {"frozen_repository_inventory_sha256": sha256_file(inventory_path)},
    )
    pipeline.fail("interrupted after acquisition")
    monkeypatch.setattr(
        "medai.workflow.run_agent",
        lambda **kwargs: pytest.fail("repository discovery must not rerun"),
    )
    monkeypatch.setattr(
        "medai.workflow.acquire_repositories",
        lambda **kwargs: pytest.fail("repository acquisition must not rerun"),
    )

    result = preflight_node(
        {"config": config, "paper_markdown": str(paper_markdown)}  # type: ignore[arg-type]
    )

    assert result["repository_inventory_path"] == str(inventory_path)
    assert PipelineState(output).is_stage_completed("preflight")


def _ambiguity_entry(**overrides):
    payload = {
        "id": "PRC-001",
        "node_id": "T1",
        "topic": "training hyperparameter",
        "repository_ids": ["R001"],
        "repository_behavior": "Uses a fixed learning rate.",
        "paper_behavior": None,
        "codegen_before": "Uses another learning rate.",
        "codegen_after": "Uses the repository learning rate.",
        "paper_relation": "unspecified",
        "repository_conflict": False,
        "scope_status": "runnable",
        "adopt": True,
        "adoption_rationale": "Repository fills a paper omission.",
        "suspicion_level": "medium",
        "integrity_flags": [],
        "repository_evidence": [
            {"source": "R001", "reference": "config.py:1", "detail": "lr=0.01"}
        ],
        "paper_evidence": [
            {"source": "paper", "reference": "Methods", "detail": "No value stated."}
        ],
        "codegen_evidence": [
            {"source": "codegen", "reference": "config.py:1", "detail": "lr=0.001"}
        ],
        "changed_files": ["config.py"],
    }
    payload.update(overrides)
    return payload


def test_ambiguity_schema_requires_suspicion_and_non_adoption_guards() -> None:
    base = {
        "version": 1,
        "repository_inventory_sha256": "1" * 64,
        "paper_graph_sha256": "2" * 64,
        "execution_scope_sha256": "3" * 64,
        "codegen_baseline_sha256": "4" * 64,
    }
    artifact = PaperRepoAmbiguity.model_validate(
        {**base, "entries": [_ambiguity_entry()]}
    )
    assert artifact.entries[0].adopt is True

    with pytest.raises(ValueError, match="suspicion level"):
        PaperRepoAmbiguity.model_validate(
            {**base, "entries": [_ambiguity_entry(suspicion_level=None)]}
        )
    with pytest.raises(ValueError, match="cannot be adopted"):
        PaperRepoAmbiguity.model_validate(
            {**base, "entries": [_ambiguity_entry(repository_conflict=True)]}
        )
    with pytest.raises(ValueError, match="cannot declare changed files"):
        PaperRepoAmbiguity.model_validate(
            {
                **base,
                "entries": [
                    _ambiguity_entry(
                        adopt=False,
                        repository_conflict=True,
                    )
                ],
            }
        )
    with pytest.raises(ValueError, match="must be adopted"):
        PaperRepoAmbiguity.model_validate(
            {
                **base,
                "entries": [
                    _ambiguity_entry(
                        adopt=False,
                        changed_files=[],
                    )
                ],
            }
        )
    with pytest.raises(ValueError, match="cannot be adopted"):
        PaperRepoAmbiguity.model_validate(
            {
                **base,
                "entries": [
                    _ambiguity_entry(integrity_flags=["outcome_guided_selection"])
                ],
            }
        )


def test_codegen_prompt_enforces_repository_isolation() -> None:
    prompt = (
        Path(__file__).parents[1] / "templates" / "codegen" / "session_instructions.md"
    ).read_text(encoding="utf-8")
    assert "The codebase is intentionally empty" in prompt
    assert "Do not search for, open, clone, download" in prompt
    assert "source-code repository" in prompt
    assert "reuse supplied repository" not in prompt.casefold()
