# AGENTS.md — working with Script-Launcher (Heelworks)

Instructions and invariants for any AI agent working on this repository.

---

## 1. Environment & Tooling

- **OS**: macOS (Apple Silicon arm64), zsh shell.
- **Node.js**: Node 22 LTS (`electron-app/.nvmrc`), npm.
- **Python**: Python 3.13 (`uv`), managed in local venv at `electron-app/resources/python/venv/`.
- **GitHub CLI**: `gh` is installed and authenticated. Never run or emit `gh auth login`.
- **Primary Frontend**: `electron-app/` (Electron + React + Vite + TypeScript/JSX).
- **Legacy Frontends**: `tui/` (Go + Bubble Tea) and `gui/` (Wails + React) are frozen/legacy. Do not touch or migrate them unless specifically requested.
- **Architecture Decisions**: Documented in `docs/decisions/` (ADR-0001 through ADR-0005).

---

## 2. Git & Pull Request Workflow (MANDATORY)

The `main` branch has branch protection rules:
- **Direct pushes to `main` are declined by GitHub.**
- All changes must be delivered via Pull Requests.
- The repository has **Auto-merge** (`allow_auto_merge: true`), **Squash Merge**, and **Delete branch on merge** enabled.

### Automated PR Procedure
Whenever committing and delivering changes, agents **must perform the entire flow automatically**. Never ask the user to manually click squash & merge on GitHub:

```bash
# 1. Create a feature branch and push to origin
git checkout -b <type>/<description>
git add .
git commit -m "<concise commit message>"
git push -u origin <type>/<description>

# 2. Open PR and immediately enable automated squash & merge
gh pr create --title "<title>" --body "<description>"
gh pr merge --squash --auto --delete-branch

# 3. Monitor PR until merged, then return to main
# Once status checks pass, GitHub automatically squashes and merges into main.
git checkout main
git pull origin main
git branch -d <type>/<description>
```

---

## 3. Electron App & Packaging Invariants

### Bundled Resources (`forge.config.ts`)
The packaged macOS `.app` bundle **must be fully self-contained** (ADR-0002).
In `electron-app/forge.config.ts`, `packagerConfig.extraResource` **must always include**:
```typescript
extraResource: [
  'resources/bin',     // Bundled binaries (ffmpeg)
  'resources/python',  // Bundled Python venv + scripts
  'resources/models',  // Bundled Piper TTS voice models
],
```
> [!CAUTION]
> If `resources/python` is removed from `extraResource`, the packaged `Heelworks.app` will fail to launch Python tools with `ENOENT: Contents/Resources/python/venv/bin/python3 not found`.

### Process Spawning & Error Handling (`src/main.ts`)
1. **Never omit `proc.on('error', ...)` on `child_process.spawn()`**:
   In Node.js, an unhandled `'error'` event emitted by `spawn()` triggers an Uncaught Exception in the Electron main process, popping up a native error dialog. Every `spawn()` call must handle `'error'`.
2. **Resilient Path Resolution**:
   `src/main.ts` must maintain fallbacks (`resolveBundledResources()` and `resolveBundledBin()`) so that running the packaged `.app` from `out/` locally still resolves resources from `electron-app/resources/` if not bundled.

---

## 4. Verification Gates (Run Before Opening a PR)

Before committing and pushing changes, verify all test suites:

```bash
# 1. Run Electron renderer unit tests (Vitest)
npm test --prefix electron-app

# 2. Run Python backend tests (pytest)
electron-app/resources/python/venv/bin/python3 -m pytest electron-app/tests/

# 3. Targeted Go tests (ONLY if Go code was modified)
go test ./registry ./tui
go vet ./registry ./tui
```

> [!WARNING]
> Never run `go test ./...` from the repository root. Go will scan and discover test packages nested inside `electron-app/node_modules/`, resulting in dozens of unrelated build failures.

---

## 5. Local Running & Testing Commands

- **Development Mode (Hot Reload)**:
  ```bash
  cd electron-app && npm start
  ```
- **Package Standalone `.app`**:
  ```bash
  cd electron-app && npm run package
  open out/Heelworks-darwin-arm64/Heelworks.app
  ```
- **Build Distributable Archive (`.zip`)**:
  ```bash
  cd electron-app && npm run make
  ```
- **Introspect Python Operations**:
  ```bash
  electron-app/resources/python/venv/bin/python3 electron-app/resources/python/scripts/docpipe.py --introspect
  ```

