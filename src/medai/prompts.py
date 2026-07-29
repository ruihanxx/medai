from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(
    os.environ.get(
        "MEDAI_TEMPLATES_DIR",
        Path(__file__).resolve().parents[2] / "templates",
    )
)
if not TEMPLATES_DIR.is_dir():
    TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_prompt(template_name: str, destination: Path, **context: Any) -> Path:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = environment.get_template(template_name).render(**context)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered.rstrip() + "\n", encoding="utf-8")
    return destination
