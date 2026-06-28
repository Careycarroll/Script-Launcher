"""Named pipelines — multi-step operations."""
import pytest
from pathlib import Path


@pytest.mark.skipif(
    not Path("/Applications/Microsoft PowerPoint.app").exists(),
    reason="Microsoft PowerPoint not installed",
)
@pytest.mark.pptx
def test_pptx_to_txt_pipeline(docpipe, fixtures_dir, tmp_outdir):
    """pptx_to_pdf -> pdf_to_txt chain."""
    import shutil
    src = tmp_outdir / "deck.pptx"
    shutil.copy(fixtures_dir / "sample.pptx", src)
    r = docpipe("pptx_to_txt", str(src))
    assert r.returncode == 0, r.stderr
    # The pipeline produces both .pdf (intermediate) and .txt (final)
    assert (tmp_outdir / "deck.txt").exists()
