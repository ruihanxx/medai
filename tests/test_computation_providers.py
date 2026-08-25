import json
from pathlib import Path

import pytest

from medai.computation_providers import get_provider_adapter, load_provider_adapters
from medai.config import RunConfig
from medai.pipeline_state import PipelineState, build_run_inputs


def _write_provider_skill(
    root: Path,
    *,
    provider: str = "fake",
    token: str = "FAKE_TOKEN",
    drive: str = "fake-drive",
) -> None:
    skill = root / "computation_provider"
    (skill / "providers").mkdir(parents=True, exist_ok=True)
    (skill / "references").mkdir(exist_ok=True)
    (skill / "cloud").mkdir(exist_ok=True)
    (skill / "scripts").mkdir(exist_ok=True)
    (skill / "references" / f"{provider}.md").write_text("reference\n", encoding="utf-8")
    (skill / "cloud" / f"{drive}.md").write_text("drive\n", encoding="utf-8")
    (skill / "scripts" / f"{provider}.py").write_text("print('adapter')\n", encoding="utf-8")
    actions = {
        action: 1
        for action in (
            "validate-state",
            "status",
            "power-on",
            "power-off",
            "reconcile",
            "release",
            "cloud-pull",
            "exec",
            "upload",
            "download",
        )
    }
    (skill / "providers" / f"{provider}.json").write_text(
        json.dumps(
            {
                "adapter_version": 1,
                "provider": provider,
                "reference": f"references/{provider}.md",
                "script": f"scripts/{provider}.py",
                "environment": [
                    {"name": token, "secret": True, "required": True},
                    {"name": "FAKE_IMAGE", "secret": False, "required": True},
                ],
                "configuration_fingerprint": ["FAKE_IMAGE"],
                "drives": {
                    drive: {
                        "reference": f"cloud/{drive}.md",
                        "source_template": "datasets/{dataset}",
                        "environment": [
                            {"name": "FAKE_DRIVE_SECRET", "secret": True, "required": True}
                        ],
                        "configuration_fingerprint": [],
                    }
                },
                "default_drive": drive,
                "actions": actions,
                "legacy_manifest": {
                    "configuration_fields": {"FAKE_IMAGE": "fake_image"}
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_fake_provider_is_discovered_and_configured_without_main_flow_changes(
    tmp_path: Path, monkeypatch
):
    skills = tmp_path / "skills"
    _write_provider_skill(skills)
    monkeypatch.setenv("MEDAI_SKILLS_DIR", str(skills))
    monkeypatch.setenv("MEDAI_COMPUTATION_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_TOKEN", "secret")
    monkeypatch.setenv("FAKE_IMAGE", "image-1")
    monkeypatch.setenv("FAKE_DRIVE_SECRET", "drive-secret")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data="dataset-a",
        siliconflow_config=None,
        clouddrive=True,
    )

    assert config.computation_provider == "fake"
    assert config.drive_provider == "fake-drive"
    assert config.cloud_source == "datasets/dataset-a"
    assert config.computation_provider_config == {
        "provider": "fake",
        "drive": "fake-drive",
        "values": {"FAKE_IMAGE": "image-1"},
    }
    assert "secret" not in json.dumps(config.computation_provider_config)
    assert "drive-secret" not in json.dumps(config.computation_provider_config)
    assert get_provider_adapter("fake").script.name == "fake.py"
    inputs = build_run_inputs(config)
    PipelineState.create(config.output, inputs)
    persisted = (config.output / "manifest.json").read_text(encoding="utf-8")
    assert "secret" not in persisted
    assert "drive-secret" not in persisted
    assert get_provider_adapter("fake").drive("fake-drive").cloud_pull_handoff is False


def test_unique_configured_provider_is_selected_without_an_environment_selector(
    tmp_path: Path, monkeypatch
):
    skills = tmp_path / "skills"
    _write_provider_skill(skills)
    monkeypatch.setenv("MEDAI_SKILLS_DIR", str(skills))
    monkeypatch.setenv("FAKE_TOKEN", "secret")
    monkeypatch.setenv("FAKE_IMAGE", "image-1")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    config = RunConfig.create(
        paper=paper,
        output=tmp_path / "output",
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )

    assert config.computation_provider == "fake"


def test_resume_inherits_recorded_provider_selection(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    _write_provider_skill(skills)
    monkeypatch.setenv("MEDAI_SKILLS_DIR", str(skills))
    monkeypatch.setenv("FAKE_TOKEN", "secret")
    monkeypatch.setenv("FAKE_IMAGE", "image-1")
    output = tmp_path / "output"
    output.mkdir()
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "inputs": {
                    "computation_provider": "fake",
                    "computation_provider_config": {
                        "provider": "fake",
                        "drive": None,
                        "values": {"FAKE_IMAGE": "image-1"},
                    },
                },
                "stages": {},
            }
        ),
        encoding="utf-8",
    )
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=None,
        siliconflow_config=None,
    )

    assert config.computation_provider == "fake"


def test_provider_loader_rejects_path_traversal(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    _write_provider_skill(skills)
    metadata = skills / "computation_provider" / "providers" / "fake.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["script"] = "../outside.py"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MEDAI_SKILLS_DIR", str(skills))

    with pytest.raises(ValueError, match="relative and contained"):
        load_provider_adapters()


def test_multiple_configured_providers_require_explicit_selection(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    _write_provider_skill(skills, provider="first", token="FIRST_TOKEN", drive="first-drive")
    _write_provider_skill(skills, provider="second", token="SECOND_TOKEN", drive="second-drive")
    monkeypatch.setenv("MEDAI_SKILLS_DIR", str(skills))
    monkeypatch.setenv("FIRST_TOKEN", "one")
    monkeypatch.setenv("SECOND_TOKEN", "two")
    monkeypatch.setenv("FAKE_IMAGE", "image")
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="Multiple computation providers"):
        RunConfig.create(
            paper=paper,
            output=tmp_path / "output",
            provider="codex",
            repo=None,
            data=None,
            siliconflow_config=None,
        )
