import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import {
  installElectronAPIMock,
  resetElectronAPIMock,
} from "./electronAPIMock";

// Install a fresh mock before every test so state never leaks between tests.
beforeEach(() => {
  installElectronAPIMock();
});

afterEach(() => {
  cleanup();
  resetElectronAPIMock();
  vi.clearAllMocks();
});
