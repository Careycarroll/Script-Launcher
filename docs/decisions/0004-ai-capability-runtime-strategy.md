# ADR-0004: Ship AI capabilities as bundled binaries, not Python libraries

- **Date:** 2026-07-02
- **Status:** Accepted
- **Deciders:** Carey Carroll

## Context

Script Launcher's roadmap includes AI-powered features: audio/video
transcription (issue #6), OCR (issue #36), text-to-speech (issue #37),
and local chat/summarization/RAG over the Obsidian vault (issue #38).

The project already ships two categories of self-contained tooling:

- A bundled Python 3.13.5 venv with pymupdf, pikepdf, Pillow, and
  python-pptx, orchestrated by `docpipe.py` (see ADR-0001, ADR-0002).
- A static `ffmpeg` binary in `resources/bin/`, invoked via subprocess.

Adding AI capabilities forces a runtime choice. Every candidate
capability (transcription, OCR, TTS, chat, embeddings) has multiple
possible runtimes:

- Python-native libraries (`faster-whisper`, `PyTorch`, `Diffusers`, etc.)
  that live inside the venv.
- Standalone C/C++ binaries (`whisper.cpp`, `llama.cpp`, `tesseract`,
  `piper`) that live in `resources/bin/` alongside ffmpeg.
- Cloud APIs (OpenAI, Deepgram, AssemblyAI) that require network access
  and API keys but zero local install cost.
- Platform-specific runtimes (MLX for Apple Silicon, CoreML) with
  significant capability but macOS lock-in beyond what the project
  already has.

The project's stated principle is "self-contained for offline usage" —
not strictly offline-only, but the local install must work without
external dependencies. Bundle size matters, especially since a
Lite/Full/AI build tier split is already planned (issue #5).

Whichever runtime pattern gets chosen for the first AI capability will
shape every subsequent AI capability. Making this decision in isolation
per-feature risks accumulating inconsistent patterns; making it once,
strategically, keeps the AI story coherent.

## Decision

All local AI capabilities ship as static C/C++ binaries in
`resources/bin/`, invoked via `docpipe.py` operations. No AI model
runtime lives inside the Python venv. Python remains the orchestration
layer, not a model host.

Committed runtimes and their capabilities:

- **whisper.cpp** — audio/video transcription (issue #6). Bundled
  binary + GGUF model file. First AI capability to ship, targeting the
  AI build tier.
- **llama.cpp** — chat, summarization, embeddings, and RAG over the
  vault (issue #38). Same GGUF ecosystem as whisper.cpp; one runtime
  pattern covers multiple capabilities.
- **Tesseract** — OCR (issue #36). Standalone C++ binary + `tessdata`
  language files. Extends `pdf_to_txt` with a fallback path for scanned
  PDFs and adds `pdf_ocr` and `image_to_txt` operations.
- **Piper** — text-to-speech (issue #37). Standalone C++ binary + ONNX
  voice files. Enables `txt_to_audio` and a `pdf_to_audio` pipeline for
  "read PDFs aloud while driving" use cases.

Cloud APIs remain viable as complementary options (user-supplied API
key, opt-in) but are not the default path. Local, offline-capable is
the primary shape.

Each capability lands as a distinct piece of work with its own issue
and PR. This ADR commits to the _pattern_, not to timing.

## Alternatives considered

### Alternative A: faster-whisper inside the Python venv

`faster-whisper` (CTranslate2-backed reimplementation of Whisper) is
architecturally clean when Python is already present. Add ~80MB of
native libraries to the bundled venv, register a new docpipe operation,
done. It parallels how pymupdf/pikepdf/Pillow are integrated.

Rejected because it optimizes for a single feature at the cost of
strategic coherence. Every _other_ planned AI capability — chat,
summarization, RAG, TTS, OCR — is better served by a standalone binary
than by a Python library. Committing to faster-whisper for transcription
makes it the only AI capability that lives inside the venv while the
rest live outside, creating two mental models where one would suffice.
The bundle size difference between faster-whisper and whisper.cpp is
small (~30–100MB); the pattern-consistency loss is larger.

### Alternative B: PyTorch-based capabilities across the board

Use PyTorch as a universal ML runtime — it can run Whisper, LLMs,
diffusion models, essentially anything. Maximum capability coverage
with one dependency.

Rejected because PyTorch adds ~500MB+ to the bundle before any model
weights, requires managing CUDA/MPS device selection, and imports a
research-oriented dependency tree into what is otherwise a lean
application. The extra capability is unused — nothing on the roadmap
requires PyTorch specifically. Cost is disproportionate.

### Alternative C: Cloud APIs only (OpenAI Whisper API, etc.)

Zero local install cost, always-current models, no bundle bloat.
Requires user-provided API key and network access.

Rejected as the _primary_ path because it breaks the self-contained
principle: users without API keys or offline access cannot use AI
features at all. Retained as a viable _secondary_ path — a user
providing an OpenAI key to run cloud transcription instead of local
whisper.cpp is a supported opt-in, not the default.

### Alternative D: MLX-native (Apple Silicon only)

MLX is Apple's Metal-native ML framework. Fastest inference on M-series
chips, smallest memory footprint, good developer ergonomics.

Rejected because it deepens the project's existing macOS coupling right
as issue #7 (OS-aware architecture) is on the backlog to _reduce_
platform lock-in. whisper.cpp and llama.cpp both use Metal acceleration
automatically on Apple Silicon without being Apple-exclusive — they
provide most of MLX's speed benefit without the platform-lock cost.

### Alternative E: ONNX Runtime as a universal backbone

Add ONNX Runtime (~30MB) to the venv and run Whisper, embeddings, TTS,
and small vision models through it. Broader compatibility than the
GGUF ecosystem.

Rejected because llama.cpp/whisper.cpp already cover the capabilities
the project cares about (chat, transcription, embeddings) with better
bundling ergonomics — a single binary with no runtime library to link.
ONNX Runtime is reconsidered if a future capability (e.g. Silero VAD,
some vision model) has no viable GGUF equivalent.

## Consequences

### Positive

- One architectural pattern covers all planned AI features: drop a
  binary into `resources/bin/`, drop a model file into
  `resources/models/` (or download on demand), register a docpipe
  operation, done. Same recipe every time.
- Python venv stays lean. AI capabilities don't bloat the venv, don't
  introduce heavyweight ML dependencies, don't force PyTorch or ONNX
  Runtime into the runtime.
- The pattern already exists (ffmpeg). New AI binaries don't require
  new concepts in `main.ts` — the runtime dispatch stays as-is.
- Apple Silicon Metal acceleration is available automatically via
  whisper.cpp and llama.cpp compile flags. No MLX lock-in needed to
  get GPU acceleration.
- Cloud API paths remain open as complementary options for users who
  prefer them, without compromising the offline-capable default.
- AI build tier (issue #5) becomes a clean packaging boundary: the
  Full build ships without AI binaries or model files; the AI build
  adds them.

### Negative

- Bundle size for the AI tier is meaningful. A minimally-useful AI
  bundle (whisper.cpp turbo model + a small llama.cpp chat model +
  Tesseract + Piper) lands somewhere between 1.5GB and 3GB depending
  on model choices. This is why the AI tier exists as a separate
  build target rather than being included in Full.
- Model file distribution is unsolved. Model files are too large to
  commit to git and too variable to ship in every release. Requires a
  separate distribution mechanism (TrueNAS hosting + first-run
  download, or per-release attached assets, or user-provided path) —
  addressed in a future ADR when the AI build tier is actually built.
- Multiple binaries in `resources/bin/` need to be kept in sync with
  their upstream projects. Each has its own release cadence, its own
  macOS ARM64 build pipeline (or requires locally-built static
  binaries). Manual work per capability.
- Voice Activity Detection (Silero VAD), if eventually needed for
  Video Silence Trim (issue #2), has no clean GGUF equivalent and
  would either force an ONNX Runtime addition or a less-accurate
  alternative. Deferred until the need is real.

### Neutral

- Cross-platform work (issue #7) requires per-OS static binaries for
  each AI capability. Not different in kind from the ffmpeg situation,
  but the surface area grows with each capability added.
- Docpipe operations remain the sole interface. UI tiles compose
  operations without needing to know which are AI-backed vs.
  pure-Python.

## Notes

Related issues:

- #2 — Video Silence Trim (may eventually want Silero VAD; see negative
  consequences)
- #5 — Lite/Full/AI build targets (AI bundle packaging)
- #6 — Whisper transcription via whisper.cpp
- #7 — OS-aware architecture
- #36 — OCR via Tesseract
- #37 — TTS via Piper
- #38 — Local chat / summarization / RAG via llama.cpp

Related ADRs:

- ADR-0001 — Operations architecture (docpipe as the orchestration layer)
- ADR-0002 — Bundled Python runtime (venv lives beside Python; this
  ADR extends the "bundled beside" principle to AI binaries)

Follow-up decisions deferred to their own ADRs:

- Model file distribution mechanism (TrueNAS vs. release assets vs.
  first-run download vs. user-supplied path).
- Voice Activity Detection runtime, if/when it becomes necessary.
