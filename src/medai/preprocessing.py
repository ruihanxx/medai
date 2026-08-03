from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
IMAGE_LINK_RE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)([^)]*\))")


def convert_pdf_to_markdown(paper: Path, preprocessing_dir: Path) -> Path:
    preprocessing_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = preprocessing_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    mineru_output_value = os.environ.get("MEDAI_MINERU_OUTPUT")
    if not mineru_output_value:
        raise RuntimeError(f"Host MinerU output is not configured for {paper}")
    mineru_output = Path(mineru_output_value)
    if not mineru_output.is_dir():
        raise RuntimeError(f"Host MinerU output directory is missing: {mineru_output}")

    markdown_files = sorted(
        mineru_output.rglob("*.md"),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if not markdown_files:
        raise RuntimeError("Host MinerU completed without producing Markdown")

    markdown_path = markdown_files[0]
    copied_images: dict[Path, Path] = {}
    for source in sorted(mineru_output.rglob("*")):
        if not source.is_file() or source.suffix.casefold() not in IMAGE_SUFFIXES:
            continue
        relative = source.relative_to(mineru_output)
        destination = artifacts_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_images[source.resolve()] = destination

    markdown = markdown_path.read_text(encoding="utf-8")

    def replace_image_link(match: re.Match[str]) -> str:
        target = match.group(2).strip("<>")
        if re.match(r"^[a-z]+://", target, flags=re.IGNORECASE):
            return match.group(0)
        source = (markdown_path.parent / target).resolve()
        destination = copied_images.get(source)
        if destination is None:
            return match.group(0)
        rewritten = destination.relative_to(preprocessing_dir).as_posix()
        return f"{match.group(1)}{rewritten}{match.group(3)}"

    output_path = preprocessing_dir / "paper.md"
    output_path.write_text(IMAGE_LINK_RE.sub(replace_image_link, markdown), encoding="utf-8")
    return output_path
