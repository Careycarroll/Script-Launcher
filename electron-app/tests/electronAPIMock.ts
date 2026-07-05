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
    PickFile: vi.fn(async () => "/mock/picked/file.pdf"),
    ListDir: vi.fn(async () => []),
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
  };

  // @ts-expect-error — attaching to window for jsdom
  window.electronAPI = electronAPI;
}

/**
 * Reset mock state between tests. Called from setup.ts afterEach.
 */
export function resetElectronAPIMock() {
  streamState = freshState();
  // @ts-expect-error
  delete window.electronAPI;
}
