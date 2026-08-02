from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
IMAGE_LINK_RE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)([^)]*\))")


def convert_pdf_to_markdown(paper: Path, preprocessing_dir: Path) -> Path:
    preprocessing_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = preprocessing_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mineru-", dir=preprocessing_dir) as temp_name:
        mineru_output = Path(temp_name)
        command = [
            os.environ.get("MINERU_COMMAND", "mineru"),
            "-p",
            str(paper),
            "-o",
            str(mineru_output),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("MINERU_TIMEOUT_SECONDS", "300")),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("MinerU is not installed or MINERU_COMMAND is invalid") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("MinerU timed out while parsing the paper") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-4000:]
            raise RuntimeError(f"MinerU failed: {detail}")

        markdown_files = sorted(
            mineru_output.rglob("*.md"),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not markdown_files:
            raise RuntimeError("MinerU completed without producing Markdown")

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
