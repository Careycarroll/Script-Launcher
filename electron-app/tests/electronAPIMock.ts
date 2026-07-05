import { vi } from "vitest";

// Handlers registered via onStreamLine / onStreamExit
type StreamLineHandler = (event: unknown) => void;
type StreamExitHandler = () => void;

interface StreamState {
  lineHandlers: Set<StreamLineHandler>;
  exitHandlers: Set<StreamExitHandler>;
  lastStartArgs: { script: string; args: string[] } | null;
  inputLog: unknown[];
  stopped: boolean;
}

let streamState: StreamState = freshState();

function freshState(): StreamState {
  return {
    lineHandlers: new Set(),
    exitHandlers: new Set(),
    lastStartArgs: null,
    inputLog: [],
    stopped: false,
  };
}

/**
 * Test helper: emit a stream line event as if the Python backend sent it.
 * Use inside a test after calling the component's start action.
 */
export function emitStreamLine(event: unknown) {
  for (const handler of streamState.lineHandlers) {
    handler(event);
  }
}

/**
 * Test helper: emit a stream exit event as if the Python process ended.
 */
export function emitStreamExit() {
  for (const handler of streamState.exitHandlers) {
    handler();
  }
}

/**
 * Test helper: inspect what the component sent to StreamStart.
 */
export function getLastStreamStart() {
  return streamState.lastStartArgs;
}

/**
 * Test helper: inspect what the component sent to StreamInput (e.g. confirm/cancel).
 */
export function getStreamInputLog() {
  return streamState.inputLog;
}

/**
 * Test helper: was StreamStop called?
 */
export function wasStreamStopped() {
  return streamState.stopped;
}

/**
 * Test helper: reset only the stream state (handlers, args, flags) without
 * wiping vi.fn implementations. Use in beforeEach for components that
 * captured window.electronAPI methods at module load.
 */
export function resetStreamState() {
  streamState.lineHandlers.clear();
  streamState.exitHandlers.clear();
  streamState.lastStartArgs = null;
  streamState.inputLog = [];
  streamState.stopped = false;
}

/**
 * Install a fresh window.electronAPI mock. Called from setup.ts before each test.
 */
export function installElectronAPIMock() {
  streamState = freshState();

  const electronAPI = {
    // ---- Streaming Python operations (Panopto, yt-dlp, docpipe streaming) ----
    StreamStart: vi.fn(async (opts: { script: string; args: string[] }) => {
      streamState.lastStartArgs = opts;
      return true;
    }),
    StreamInput: vi.fn(async (payload: unknown) => {
      streamState.inputLog.push(payload);
      return true;
    }),
    StreamStop: vi.fn(async () => {
      streamState.stopped = true;
      return true;
    }),
    onStreamLine: vi.fn((handler: StreamLineHandler) => {
      streamState.lineHandlers.add(handler);
    }),
    onStreamExit: vi.fn((handler: StreamExitHandler) => {
      streamState.exitHandlers.add(handler);
    }),
    offStreamLine: vi.fn(() => {
      streamState.lineHandlers.clear();
    }),
    offStreamExit: vi.fn(() => {
      streamState.exitHandlers.clear();
    }),

    // ---- Dialogs & filesystem ----
    PickFolder: vi.fn(async () => "/mock/picked/folder"),
    ListDir: vi.fn(async () => []),
    PickFile: vi.fn(async () => "/mock/picked/file.pdf"),
    SaveFile: vi.fn(async () => ({ saved: true, path: "/mock/saved" })),
    OpenExternal: vi.fn(async () => ({ opened: true })),

    // ---- Registry / scripts ----
    getGroups: vi.fn(async () => ({})),
    runScript: vi.fn(async () => ({ output: "" })),

    // ---- Terminal / PTY ----
    ptyShell: vi.fn(async () => true),
    ptyCreate: vi.fn(async () => true),
    ptyInput: vi.fn(),
    ptyResize: vi.fn(),
    ptyKill: vi.fn(),
    onPtyOutput: vi.fn(),
    onPtyExit: vi.fn(),

    // ---- Vault ----
    vaultStart: vi.fn(async () => ({ started: true })),
    vaultStop: vi.fn(async () => ({ stopped: true })),
    vaultQuery: vi.fn(async () => ({})),

    RunScript: vi.fn(async () => ({ output: "ok" })),
    AnalyzeBookmarks: vi.fn(async () => ({
      info: "3 chapters detected",
      entries: [
        [1, "Introduction"],
        [12, "Chapter 1"],
        [45, "Chapter 2"],
      ],
    })),
  };

  // @ts-expect-error — attaching to window for jsdom
  window.electronAPI = electronAPI;
}

/**
 * Reset mock state between tests. Called from setup.ts afterEach.
 */
export function resetElectronAPIMock() {
  streamState = freshState();
  // Do NOT delete window.electronAPI — components that captured its methods
  // at module load time still hold references. Just reset the stream state;
  // per-test method reset happens via installElectronAPIMock() in beforeEach.
}
