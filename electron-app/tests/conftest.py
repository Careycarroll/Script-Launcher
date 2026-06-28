"""Shared pytest fixtures for docpipe tests."""
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
DOCPIPE = REPO_ROOT / "resources" / "python" / "scripts" / "docpipe.py"
PYTHON = REPO_ROOT / "resources" / "python" / "venv" / "bin" / "python3"
FIXTURES = HERE / "fixtures"


@pytest.fixture
def docpipe():
    """Return a callable that invokes docpipe.py with given args."""
    def _run(*args, cwd=None) -> subprocess.CompletedProcess:
        cmd = [str(PYTHON), str(DOCPIPE), *args]
        return subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    return _run


@pytest.fixture
def tmp_outdir(tmp_path):
    """Temp directory pytest cleans up automatically."""
    out = tmp_path / "out"
    out.mkdir()
    return out


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture(autouse=True)
def cleanup_fixture_outputs():
    """Remove generated outputs in fixtures/ after each test."""
    yield
    for pattern in ("*.txt", "*_stripped.pdf", "*_merged.pdf",
                    "*_bookmarked.pdf", "*_split.txt"):
        for f in FIXTURES.glob(pattern):
            f.unlink()
    for f in FIXTURES.glob("*_split_*.pdf"):
        f.unlink()
