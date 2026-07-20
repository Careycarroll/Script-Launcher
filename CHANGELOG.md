# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Text → Audio** now supports mp3/m4a/mp4 output with bitrate control, via a text_to_audio.py wrapper.
- **Video → Audio** Media tool for single-file extraction with mp3/m4a/wav output and optional EBU R128 loudness normalization.
- **Text → Audio document tool** using local Piper TTS.
- Bundled Piper voice models for Ryan, HFC Female, and Bryce.
- `tts_piper.py` script under `electron-app/resources/python/scripts/`.
- Renderer test workflow for Vitest / React Testing Library.
- Component and workflow tests for WidgetRenderer, BookmarkEditor, Vault panels, Panopto downloader, and generic yt-dlp downloader.

### Changed

- Polished Vault Workbench UX, including auto-reindex behavior and TXT export.
- Improved Vite dev-mode behavior.
- Expanded Electron registry coverage for current Documents, Vault, Media, and Developer tools.

### Documentation

- Refresh root README and Electron README to reflect Electron-primary architecture, launchpad/domain tiles, current test commands, Piper TTS, and post-v0.5.1 project state.

## [0.5.1] - 2026-07-05

### Added

- Generic `yt-dlp` downloader for Media workflows.
- Test coverage for generic downloader behavior.

### Changed

- Set Electron app version to `0.5.1`.

## [0.5.0] - 2026-07-05

### Added

- Vault Workbench foundation and launchpad/domain tile scaffold.
- Vault indexer standalone mode and JSON stdin/stdout service mode.
- Vault metrics report view.
- Vault graph canvas.
- File-level exclusion support with default exclusion for Vault Health Report.
- Panopto video downloader workflow.
- Metadata review, editable output title, and smoother media progress behavior.
- ADR-0005 for Vault Workbench architecture.

### Changed

- Migrated interactive terminal behavior into tile-local overlay flow.
- Formalized registry `component` field for bespoke React tile experiences.
- Added `domain` metadata to Electron registry entries.
- Renamed Electron app to **Heelworks** and added branded app icon.

### Fixed

- Restored Vault Workbench save/open external wiring.
- Improved Panopto output-folder auto-increment behavior.
- Cleaned App.css artifacts from patch application.
- Ignored nested `.DS_Store` files.

## [0.4.0] - 2026-06-27

First tagged release. Captures the adoption of a formal release workflow with tags, changelog, GitHub Releases, and CI.

### Added

- GitHub Actions pytest workflow.
- CI status badge in root README.
- PR template.
- MIT license.
- Operations architecture for `docpipe.py`.
- Document operations: `pdf_to_txt`, `images_to_pdf`, `pptx_to_pdf`, `pdf_merge`, `pdf_strip`, `pdf_bookmark_analyze`, `pdf_bookmark_add`, and `pdf_split`.
- `pptx_to_txt` pipeline.
- PDF Bookmarks analyze/edit/apply workflow.
- Live theme drawer with built-in presets.
- Bundled Python runtime for Electron document tools.
- Bundled ffmpeg support for Electron media workflows.
- Architecture decision records for operations, bundled Python, and launchpad/domain tiles.

### Changed

- Replaced README backlog lists with GitHub Issues as the canonical backlog.
- Removed Electron dependency on poppler and ghostscript for document operations.

[Unreleased]: https://github.com/Careycarroll/Script-Launcher/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/Careycarroll/Script-Launcher/releases/tag/v0.5.1
[0.5.0]: https://github.com/Careycarroll/Script-Launcher/releases/tag/v0.5.0
[0.4.0]: https://github.com/Careycarroll/Script-Launcher/releases/tag/v0.4.0
