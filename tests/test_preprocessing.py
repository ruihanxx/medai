from pathlib import Path

from medai.preprocessing import convert_pdf_to_markdown


def test_mineru_images_are_copied_and_links_rewritten(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    preprocessing = tmp_path / "preprocessing"
    mineru_output = tmp_path / "mineru-output"
    document = mineru_output / "paper" / "auto"
    images = document / "images"
    images.mkdir(parents=True)
    (images / "figure.png").write_bytes(b"png")
    (document / "paper.md").write_text(
        "# Paper\n\n![Figure](images/figure.png)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEDAI_MINERU_OUTPUT", str(mineru_output))

    output = convert_pdf_to_markdown(paper, preprocessing)

    markdown = output.read_text(encoding="utf-8")
    assert "artifacts/paper/auto/images/figure.png" in markdown
    assert (preprocessing / "artifacts" / "paper" / "auto" / "images" / "figure.png").is_file()


def test_mineru_failure_is_explicit(tmp_path: Path, monkeypatch):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    mineru_output = tmp_path / "mineru-output"
    mineru_output.mkdir()
    monkeypatch.setenv("MEDAI_MINERU_OUTPUT", str(mineru_output))
    try:
        convert_pdf_to_markdown(paper, tmp_path / "preprocessing")
    except RuntimeError as exc:
        assert "without producing Markdown" in str(exc)
    else:
        raise AssertionError("MinerU failure was not raised")
