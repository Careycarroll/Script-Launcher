import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import PanoptoDownloader from "../src/tiles/PanoptoDownloader.jsx";
import {
  emitStreamLine,
  emitStreamExit,
  getLastStreamStart,
  getStreamInputLog,
  wasStreamStopped,
  resetStreamState,
} from "./electronAPIMock";

// Same pattern as BookmarkEditor: PanoptoDownloader destructures window.electronAPI
// at module load. Grab the captured references and reset behavior each test.
// @ts-expect-error
const streamStartMock = window.electronAPI.StreamStart as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const streamInputMock = window.electronAPI.StreamInput as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const streamStopMock = window.electronAPI.StreamStop as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const onStreamLineMock = window.electronAPI.onStreamLine as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const onStreamExitMock = window.electronAPI.onStreamExit as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const offStreamLineMock = window.electronAPI.offStreamLine as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const offStreamExitMock = window.electronAPI.offStreamExit as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const pickFolderMock = window.electronAPI.PickFolder as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const openExternalMock = window.electronAPI.OpenExternal as ReturnType<
  typeof vi.fn
>;
// @ts-expect-error
const listDirMock = window.electronAPI.ListDir as ReturnType<typeof vi.fn>;

const clipReadMock = navigator.clipboard.readText as ReturnType<typeof vi.fn>;

beforeEach(() => {
  // Stream methods: mockClear preserves implementations (which register handlers
  // into streamState). mockReset would wipe those implementations and break
  // emitStreamLine / emitStreamExit.
  streamStartMock.mockClear();
  streamInputMock.mockClear();
  streamStopMock.mockClear();
  onStreamLineMock.mockClear();
  onStreamExitMock.mockClear();
  offStreamLineMock.mockClear();
  offStreamExitMock.mockClear();
  resetStreamState();

  // Non-stream methods: safe to mockReset since we always re-set the impl below.
  pickFolderMock.mockReset().mockImplementation(async () => "/mock/out");
  openExternalMock
    .mockReset()
    .mockImplementation(async () => ({ opened: true }));
  listDirMock.mockReset().mockImplementation(async () => []);
  clipReadMock.mockReset().mockImplementation(async () => "");
  localStorage.clear();
});

// ─────────────────────────────────────────────────────────────
// Initial state
// ─────────────────────────────────────────────────────────────

describe("PanoptoDownloader — initial state", () => {
  it("Download button disabled when URL is empty", async () => {
    render(<PanoptoDownloader />);
    const btn = await screen.findByRole("button", { name: /^Download$/i });
    expect(btn).toBeDisabled();
  });

  it("Download button enabled when url/outDir/prefix all set", async () => {
    render(<PanoptoDownloader />);
    fireEvent.change(screen.getByPlaceholderText(/panopto.com/i), {
      target: {
        value: "https://demo.panopto.com/Panopto/Pages/Viewer.aspx?id=abc",
      },
    });
    // outDir is picked via PickFolder click
    fireEvent.click(screen.getByRole("button", { name: /^Pick$/i }));
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /^Download$/i });
      expect(btn).not.toBeDisabled();
    });
  });

  it("clipboard auto-prefills URL when clipboard has a Panopto URL", async () => {
    clipReadMock.mockImplementation(async () => "https://x.panopto.com/foo");
    render(<PanoptoDownloader />);
    await waitFor(() => {
      const input = screen.getByPlaceholderText(
        /panopto.com/i,
      ) as HTMLInputElement;
      expect(input.value).toBe("https://x.panopto.com/foo");
    });
  });

  it("clipboard does NOT prefill when clipboard has a non-Panopto URL", async () => {
    clipReadMock.mockImplementation(
      async () => "https://youtube.com/watch?v=abc",
    );
    render(<PanoptoDownloader />);
    // Give the effect a tick
    await new Promise((r) => setTimeout(r, 10));
    const input = screen.getByPlaceholderText(
      /panopto.com/i,
    ) as HTMLInputElement;
    expect(input.value).toBe("");
  });
});

// ─────────────────────────────────────────────────────────────
// Prefix auto-detect
// ─────────────────────────────────────────────────────────────

describe("PanoptoDownloader — prefix auto-detect", () => {
  it("detects next prefix after existing NN. files", async () => {
    listDirMock.mockImplementation(async () => ["01. Foo.mp4", "03. Bar.mp4"]);
    render(<PanoptoDownloader />);
    fireEvent.click(screen.getByRole("button", { name: /^Pick$/i }));
    await waitFor(() => {
      const prefixInput = screen.getByPlaceholderText("01") as HTMLInputElement;
      expect(prefixInput.value).toBe("04");
    });
  });

  it("keeps default prefix when directory is empty", async () => {
    listDirMock.mockImplementation(async () => []);
    render(<PanoptoDownloader />);
    fireEvent.click(screen.getByRole("button", { name: /^Pick$/i }));
    // Empty dir → maxN = 0 → next = 01
    await waitFor(() => {
      const prefixInput = screen.getByPlaceholderText("01") as HTMLInputElement;
      expect(prefixInput.value).toBe("01");
    });
  });
});

// ─────────────────────────────────────────────────────────────
// Helper: get the streamLine handler the component registered
// ─────────────────────────────────────────────────────────────
function getRegisteredStreamLineHandler() {
  const calls = onStreamLineMock.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as (msg: any) => void;
}
function getRegisteredStreamExitHandler() {
  const calls = onStreamExitMock.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as () => void;
}

async function primeReadyState() {
  fireEvent.change(screen.getByPlaceholderText(/panopto.com/i), {
    target: { value: "https://x.panopto.com/foo" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Pick$/i }));
  await waitFor(() => {
    const btn = screen.getByRole("button", { name: /^Download$/i });
    expect(btn).not.toBeDisabled();
  });
}

// ─────────────────────────────────────────────────────────────
// Download start → metadata → confirm/cancel
// ─────────────────────────────────────────────────────────────

describe("PanoptoDownloader — start / metadata / confirm", () => {
  it("startDownload calls StreamStart with correct script and flag args", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));

    await waitFor(() => expect(streamStartMock).toHaveBeenCalledTimes(1));
    const opts = streamStartMock.mock.calls[0][0];
    expect(opts.script).toBe("python/scripts/panopto_download.py");
    expect(opts.args).toContain("https://x.panopto.com/foo");
    expect(opts.args).toContain("--out-dir");
    expect(opts.args).toContain("/mock/out");
    expect(opts.args).toContain("--captions");
    expect(opts.args).toContain("--embed-subs");
  });

  it("metadata event shows review UI with editable title", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => {
      emitStreamLine({
        type: "metadata",
        title: "Lecture 03",
        width: 1920,
        height: 1080,
        duration_seconds: 1830,
      });
    });

    expect(screen.getByText(/Review & confirm/i)).toBeInTheDocument();
    const titleInput = screen.getByPlaceholderText(
      /video title/i,
    ) as HTMLInputElement;
    expect(titleInput.value).toBe("Lecture 03");
  });

  it("Confirm & download sends action:confirm with edited title", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => {
      emitStreamLine({ type: "metadata", title: "Original" });
    });
    const titleInput = screen.getByPlaceholderText(/video title/i);
    fireEvent.change(titleInput, { target: { value: "Renamed" } });
    fireEvent.click(
      screen.getByRole("button", { name: /Confirm & download/i }),
    );

    await waitFor(() => expect(streamInputMock).toHaveBeenCalledTimes(1));
    expect(streamInputMock).toHaveBeenCalledWith({
      action: "confirm",
      title: "Renamed",
    });
    // Metadata UI should be gone
    expect(screen.queryByText(/Review & confirm/i)).not.toBeInTheDocument();
  });

  it("Cancel in metadata view sends action:cancel and clears review UI", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => {
      emitStreamLine({ type: "metadata", title: "Foo" });
    });
    // Two Cancel buttons could exist in DOM; scope to the metadata block
    const cancelBtns = screen.getAllByRole("button", { name: /^Cancel$/i });
    // The one inside metadata review is next to Confirm & download
    fireEvent.click(cancelBtns[cancelBtns.length - 1]);

    await waitFor(() => expect(streamInputMock).toHaveBeenCalledTimes(1));
    expect(streamInputMock).toHaveBeenCalledWith({ action: "cancel" });
    expect(screen.queryByText(/Review & confirm/i)).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// Progress + conflict
// ─────────────────────────────────────────────────────────────

describe("PanoptoDownloader — progress and conflict", () => {
  it("progress event renders bar with correct percent", async () => {
    const { container } = render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => {
      emitStreamLine({
        type: "progress",
        percent: 42.5,
        downloaded_bytes: 1024,
        total_bytes: 2048,
        speed_bps: 512,
        eta_seconds: 30,
      });
    });

    expect(screen.getByText(/42\.5%/)).toBeInTheDocument();
    const bar = container.querySelector(".panopto-progress-bar") as HTMLElement;
    expect(bar).toBeInTheDocument();
    expect(bar.style.width).toBe("42.5%");
  });

  it("conflict event hides progress and shows three response buttons", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => {
      emitStreamLine({
        type: "progress",
        percent: 10,
        downloaded_bytes: 0,
        total_bytes: 100,
      });
    });
    act(() => {
      emitStreamLine({ type: "conflict", message: "File exists" });
    });

    expect(screen.getByText("File exists")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Overwrite$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Use next number/i }),
    ).toBeInTheDocument();
    // Progress bar should not render while conflict is up
    expect(document.querySelector(".panopto-progress-bar")).toBeNull();
  });

  it("conflict Overwrite sends action:overwrite", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());
    act(() => emitStreamLine({ type: "conflict", message: "exists" }));

    fireEvent.click(screen.getByRole("button", { name: /^Overwrite$/i }));
    await waitFor(() => expect(streamInputMock).toHaveBeenCalledTimes(1));
    expect(streamInputMock).toHaveBeenCalledWith({ action: "overwrite" });
  });

  it("conflict Use next number sends action:increment", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());
    act(() => emitStreamLine({ type: "conflict", message: "exists" }));

    fireEvent.click(screen.getByRole("button", { name: /Use next number/i }));
    await waitFor(() => expect(streamInputMock).toHaveBeenCalledTimes(1));
    expect(streamInputMock).toHaveBeenCalledWith({ action: "increment" });
  });

  it("conflict Cancel sends action:cancel", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());
    act(() => emitStreamLine({ type: "conflict", message: "exists" }));

    // The Cancel inside the conflict block
    const cancelBtns = screen.getAllByRole("button", { name: /^Cancel$/i });
    fireEvent.click(cancelBtns[cancelBtns.length - 1]);
    await waitFor(() => expect(streamInputMock).toHaveBeenCalledTimes(1));
    expect(streamInputMock).toHaveBeenCalledWith({ action: "cancel" });
  });
});

// ─────────────────────────────────────────────────────────────
// Done + reveal + exit
// ─────────────────────────────────────────────────────────────

describe("PanoptoDownloader — done and cleanup", () => {
  it("done event shows result path and Show in Finder button", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => emitStreamLine({ type: "done", path: "/mock/out/01. Foo.mp4" }));

    expect(
      screen.getByText(/Downloaded to \/mock\/out\/01\. Foo\.mp4/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Show in Finder/i }),
    ).toBeInTheDocument();
  });

  it("Show in Finder calls OpenExternal with file:// URL of parent dir", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());
    act(() => emitStreamLine({ type: "done", path: "/mock/out/01. Foo.mp4" }));

    fireEvent.click(screen.getByRole("button", { name: /Show in Finder/i }));
    await waitFor(() => expect(openExternalMock).toHaveBeenCalledTimes(1));
    const url = openExternalMock.mock.calls[0][0] as string;
    expect(url.startsWith("file:///mock/out")).toBe(true);
  });

  it("streamExit calls offStreamLine and offStreamExit", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());

    act(() => emitStreamExit());
    expect(offStreamLineMock).toHaveBeenCalled();
    expect(offStreamExitMock).toHaveBeenCalled();
  });

  it("Cancel button (during download) calls StreamStop", async () => {
    render(<PanoptoDownloader />);
    await primeReadyState();
    fireEvent.click(screen.getByRole("button", { name: /^Download$/i }));
    await waitFor(() => expect(streamStartMock).toHaveBeenCalled());
    // No metadata, no conflict → the top-level Cancel button is visible
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));
    await waitFor(() => expect(streamStopMock).toHaveBeenCalledTimes(1));
  });
});
