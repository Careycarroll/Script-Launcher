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
