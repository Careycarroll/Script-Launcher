# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-06-27

First tagged release. Captures the state of the project at the point of adopting
a professional release workflow (tags, changelog, GitHub Releases).

### Added
- **Operations architecture** for `docpipe.py` — named operations registry with
  format/arity declarations, per-operation namespaced flags, and `--list` /
  `--introspect` diagnostics.
- **8 operations**: `pdf_to_txt`, `images_to_pdf`, `pptx_to_pdf`, `pdf_merge`,
  `pdf_strip`, `pdf_bookmark_analyze`, `pdf_bookmark_add`, `pdf_split`.
- **1 pipeline**: `pptx_to_txt` (chained `pptx_to_pdf` → `pdf_to_txt`).
- **Unified PDF Bookmarks workflow** — two-stage detect/edit/apply UI with
  embedded outline detection plus font-signature fallback.
- **Live theme drawer** — 14 CSS variables across 3 groups, three built-in
  presets (UNC Night, Dracula, Nord), persisted to `localStorage`.
- **Output panel UI improvements** — clearer progress and error surfaces.
- **Bundled Python runtime** — self-contained venv (Python 3.13.5) with
  pymupdf, pikepdf, Pillow. No Homebrew dependencies for document scripts.
- **Bundled ffmpeg** — static darwin-arm64 binary in `resources/bin/`.
- **PR template** at `.github/pull_request_template.md`.
- **MIT LICENSE**.
- **GitHub Issues** as the canonical backlog (10 issues, 2 milestones, 14
  namespaced labels).

### Changed
- Both READMEs replaced inline backlog lists with a link to GitHub Issues.

### Removed
- External dependency on poppler and ghostscript for the Electron frontend
  (replaced by bundled Python pipeline).

[Unreleased]: https://github.com/Careycarroll/Script-Launcher/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Careycarroll/Script-Launcher/releases/tag/v0.4.0
