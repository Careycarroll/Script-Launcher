"""Per-operation smoke tests — does each operation produce valid output?"""
import json
import shutil
import pytest


def test_pdf_to_txt(docpipe, fixtures_dir):
    r = docpipe("pdf_to_txt", str(fixtures_dir / "sample.pdf"))
    assert r.returncode == 0, r.stderr
    out = fixtures_dir / "sample.txt"
    assert out.exists()
    assert "Hello from page 1" in out.read_text()


def test_pdf_to_txt_layout_option(docpipe, fixtures_dir):
    r = docpipe(
        "pdf_to_txt", str(fixtures_dir / "sample.pdf"),
        "--pdf_to_txt-layout", "plain",
    )
    assert r.returncode == 0, r.stderr


def test_images_to_pdf(docpipe, fixtures_dir, tmp_outdir):
    out_pdf = tmp_outdir / "combined.pdf"
    r = docpipe(
        "images_to_pdf",
        str(fixtures_dir / "red.png"),
        str(fixtures_dir / "blue.png"),
        "--out", str(out_pdf),
    )
    assert r.returncode == 0, r.stderr
    assert out_pdf.exists()
    assert out_pdf.stat().st_size > 0


def test_pdf_merge(docpipe, fixtures_dir, tmp_outdir):
    out_pdf = tmp_outdir / "merged.pdf"
    r = docpipe(
        "pdf_merge",
        str(fixtures_dir / "sample.pdf"),
        str(fixtures_dir / "sample2.pdf"),
        "--out", str(out_pdf),
    )
    assert r.returncode == 0, r.stderr
    assert out_pdf.exists()


def test_pdf_strip(docpipe, fixtures_dir):
    r = docpipe("pdf_strip", str(fixtures_dir / "sample.pdf"))
    assert r.returncode == 0, r.stderr
    out = fixtures_dir / "sample_stripped.pdf"
    assert out.exists()


def test_pdf_split_every_n(docpipe, fixtures_dir, tmp_outdir):
    src = tmp_outdir / "sample.pdf"
    shutil.copy(fixtures_dir / "sample.pdf", src)
    r = docpipe("pdf_split", str(src), "--pdf_split-mode", "every", "--pdf_split-every", "1")
    assert r.returncode == 0, r.stderr
    # Split outputs may use various naming conventions — accept anything matching the stem
    parts = [p for p in tmp_outdir.glob("sample*.pdf") if p.name != "sample.pdf"]
    assert len(parts) >= 2, f"expected >=2 split parts, found: {[p.name for p in tmp_outdir.iterdir()]}"


def test_pdf_bookmark_analyze(docpipe, fixtures_dir):
    r = docpipe("pdf_bookmark_analyze", str(fixtures_dir / "sample.pdf"))
    assert r.returncode == 0, r.stderr
    # Output may contain progress lines + JSON; find the JSON object
    json_line = next(
        (line for line in r.stdout.splitlines() if line.strip().startswith("{")),
        None,
    )
    assert json_line, f"no JSON in output: {r.stdout!r}"
    data = json.loads(json_line)
    assert "source" in data or "bookmarks" in data


def test_pdf_bookmark_add(docpipe, fixtures_dir, tmp_outdir):
    src = tmp_outdir / "sample.pdf"
    shutil.copy(fixtures_dir / "sample.pdf", src)
    # --pdf_bookmark_add-list takes inline content, not a file path
    r = docpipe(
        "pdf_bookmark_add", str(src),
        "--pdf_bookmark_add-list", "1:Introduction\n2:Conclusion",
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_outdir / "sample_bookmarked.pdf").exists()


@pytest.mark.pptx
def test_pptx_to_pdf(docpipe, fixtures_dir, tmp_outdir):
    out_pdf = tmp_outdir / "deck.pdf"
    r = docpipe(
        "pptx_to_pdf", str(fixtures_dir / "sample.pptx"),
        "--out", str(out_pdf),
    )
    assert r.returncode == 0, r.stderr
    assert out_pdf.exists()
