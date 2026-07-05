import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import {
  installElectronAPIMock,
  resetElectronAPIMock,
} from "./electronAPIMock";

// Install once at module load so components that destructure window.electronAPI
// at import time (e.g. BookmarkEditor) see it. beforeEach reinstalls for isolation.
installElectronAPIMock();

// jsdom doesn't implement navigator.clipboard. Provide a mockable shim so
// components that read/write the clipboard (Panopto, generic yt-dlp) don't crash.
Object.defineProperty(navigator, "clipboard", {
  value: {
    readText: vi.fn(async () => ""),
    writeText: vi.fn(async () => {}),
  },
  configurable: true,
});

// jsdom stubs alert to throw. Some components (VaultWorkbench.runAlsoInDomain)
// call alert on error paths; silence it.
window.alert = vi.fn();

beforeEach(() => {
  // Do NOT reinstall the mock — components capture method references at module
  // load and would lose them. Individual tests reset method behavior via
  // mockReset()/mockImplementation() on the captured references.
});

afterEach(() => {
  cleanup();
  resetElectronAPIMock();
  vi.clearAllMocks();
});
