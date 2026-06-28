# ADR-0002: Bundle Python runtime instead of using system dependencies

- **Date:** 2026-06-18 (retroactive)
- **Status:** Accepted
- **Deciders:** Carey Carroll

## Context

The TUI and Wails GUI frontends rely on Homebrew-installed tools (`pdftotext`
from poppler, `gs` from ghostscript) for document operations. This works on my
machine but means anyone running these frontends needs `brew install poppler
ghostscript`. The Electron frontend was originally going to follow the same
pattern.

Two problems made me reconsider:

1. Electron is the only frontend I'm actively developing. The TUI/GUI are
   frozen test beds. Electron is the one that needs to be self-contained
   because it's the one I want to be able to install fresh on a new machine
   and have it work.
2. The operations architecture refactor (ADR-0001) gave me an opportunity to
   replace the external tools with Python libraries (`pymupdf`, `pikepdf`,
   `Pillow`) that do the work more flexibly and don't depend on system state.

## Decision

Bundle a Python 3.13.5 virtual environment into the Electron app under
`resources/python/venv/`. Include `pymupdf`, `pikepdf`, and `Pillow` as
dependencies. Replace `pdftotext` and `ghostscript` calls in the Electron
pipeline with direct library use. Also bundle a static `ffmpeg` binary under
`resources/bin/` for Lecture Merge.

The Electron app's `PATH` is prepended with `resources/bin/` at startup so
bundled tools always take precedence over system-installed versions.

## Alternatives considered

### Require Homebrew dependencies
What the TUI/GUI do. Rejected for Electron because the explicit goal of the
Electron frontend is "install and run, no external setup." Requiring brew
contradicts that.

### Use pure-JavaScript libraries via npm
There are JS libraries that do PDF manipulation (pdf-lib, pdfjs). Rejected
because the Python ecosystem for PDFs is significantly more mature, and I
already had Python scripts working. Switching to JS would mean reimplementing
several months of work with worse tools.

### Use a system Python with pip install on first run
Considered. Rejected because: (a) it makes the first launch unreliable —
network required, pip can fail, system Python version varies; (b) it adds
runtime complexity (version checks, install state); (c) the bundled venv
approach is what every other Electron-with-Python app does (Anki, Calibre).

### Use PyOxidizer or similar to compile Python to a single binary
Considered. Rejected as overcomplication for the size savings it would
provide. The bundled venv adds ~100MB. PyOxidizer would reduce that but
introduce a complex build step and would require updating to Python 3.13
support which lagged at the time.

## Consequences

### Positive
- The Electron app is genuinely self-contained on macOS arm64.
- No "did you brew install ghostscript?" support questions to future-self.
- Python libraries (`pymupdf`, `pikepdf`) are more flexible than CLI tools —
  e.g., the PPTX compression preset that walks image streams and downsamples
  in lockstep with their SMasks would not be possible via ghostscript.
- Reproducibility: pinning the Python version means the bundled runtime
  doesn't change underneath the operations.

### Negative
- Bundle size grew by ~150MB (Python + libraries).
- Build time during `npm run make` is longer because of the venv copy.
- Cross-platform support (Windows, Linux) would require bundling separate
  venvs per platform — defer until needed (see issue #7 for OS-aware
  architecture).
- The venv must be regenerated on Python minor version changes.

### Neutral
- Documentation in the README now distinguishes "TUI/GUI dependencies" from
  "Electron dependencies."

## Notes

- Bundle structure: `resources/python/venv/` (Python + libraries),
  `resources/bin/ffmpeg` (static darwin-arm64 binary).
- TUI/GUI frontends continue to use Homebrew dependencies and are
  intentionally not migrated. They're frozen test beds.
