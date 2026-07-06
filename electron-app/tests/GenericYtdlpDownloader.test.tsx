import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import GenericYtdlpDownloader, {
  isLikelyUrl,
  looksLikePlaylistUrl,
  compactIndexes,
} from "../src/tiles/GenericYtdlpDownloader.jsx";
import {
  emitStreamLine,
  emitStreamExit,
  getLastStreamStart,
  getStreamInputLog,
  resetStreamState,
} from "./electronAPIMock";

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
const listDirMock = window.electronAPI.ListDir as ReturnType<typeof vi.fn>;

const clipReadMock = navigator.clipboard.readText as ReturnType<typeof vi.fn>;

beforeEach(() => {
  streamStartMock.mockClear();
  streamInputMock.mockClear();
  streamStopMock.mockClear();
  onStreamLineMock.mockClear();
  onStreamExitMock.mockClear();
  offStreamLineMock.mockClear();
  offStreamExitMock.mockClear();
  resetStreamState();

  pickFolderMock.mockReset().mockImplementation(async () => "/mock/out");
  listDirMock.mockReset().mockImplementation(async () => []);
  clipReadMock.mockReset().mockImplementation(async () => "");
  localStorage.clear();
});

// ─────────────────────────────────────────────────────────────
// Pure helpers
// ─────────────────────────────────────────────────────────────

describe("isLikelyUrl", () => {
  it("returns true for http and https", () => {
    expect(isLikelyUrl("http://example.com")).toBe(true);
    expect(isLikelyUrl("https://example.com/path?a=1")).toBe(true);
  });

  it("returns false for empty, whitespace, or non-URL strings", () => {
    expect(isLikelyUrl("")).toBe(false);
    expect(isLikelyUrl(null as any)).toBe(false);
    expect(isLikelyUrl(undefined as any)).toBe(false);
    expect(isLikelyUrl("not a url")).toBe(false);
    expect(isLikelyUrl("ftp://example.com")).toBe(false);
  });
});

describe("looksLikePlaylistUrl", () => {
  it("detects list= query param", () => {
    expect(
      looksLikePlaylistUrl("https://youtube.com/watch?v=abc&list=PLxyz"),
    ).toBe(true);
  });

  it("detects /playlist path", () => {
    expect(
      looksLikePlaylistUrl("https://youtube.com/playlist?list=PLxyz"),
    ).toBe(true);
  });

  it("detects /sets/ (SoundCloud style)", () => {
    expect(
      looksLikePlaylistUrl("https://soundcloud.com/user/sets/my-set"),
    ).toBe(true);
  });

  it("detects /album/ (Bandcamp style)", () => {
    expect(looksLikePlaylistUrl("https://artist.bandcamp.com/album/foo")).toBe(
      true,
    );
  });

  it("detects /channel/", () => {
    expect(looksLikePlaylistUrl("https://youtube.com/channel/UCxyz")).toBe(
      true,
    );
  });

  it("detects /@ (channel handle)", () => {
    expect(looksLikePlaylistUrl("https://youtube.com/@somechannel")).toBe(true);
  });

  it("returns false for a plain video URL", () => {
    expect(looksLikePlaylistUrl("https://youtube.com/watch?v=abc")).toBe(false);
    expect(looksLikePlaylistUrl("https://vimeo.com/123456")).toBe(false);
  });

  it("returns false for empty / null", () => {
    expect(looksLikePlaylistUrl("")).toBe(false);
    expect(looksLikePlaylistUrl(null as any)).toBe(false);
  });
});

describe("compactIndexes", () => {
  it("returns empty string for empty input", () => {
    expect(compactIndexes([])).toBe("");
  });

  it("returns single index unchanged", () => {
    expect(compactIndexes([5])).toBe("5");
  });

  it("collapses contiguous range", () => {
    expect(compactIndexes([1, 2, 3, 4, 5])).toBe("1-5");
  });

  it("handles multiple ranges with gaps", () => {
    expect(compactIndexes([1, 2, 3, 5, 7, 8, 10])).toBe("1-3,5,7-8,10");
  });

  it("dedupes and sorts input", () => {
    expect(compactIndexes([3, 1, 2, 3, 1])).toBe("1-3");
  });

  it("coerces string indexes to numbers", () => {
    expect(compactIndexes(["1", "2", "3"] as any)).toBe("1-3");
  });

  it("excludes zero-index items (playlist is 1-based)", () => {
    // .filter(Boolean) drops 0
    expect(compactIndexes([0, 1, 2, 3])).toBe("1-3");
  });
});

// ─────────────────────────────────────────────────────────────
// URL handling
// ─────────────────────────────────────────────────────────────

describe("GenericYtdlpDownloader — URL handling", () => {
  it("clipboard prefill sets allowPlaylist for playlist URL", async () => {
    clipReadMock.mockImplementation(
      async () => "https://youtube.com/playlist?list=PLxyz",
    );
    render(<GenericYtdlpDownloader />);
    await waitFor(() => {
      const cb = screen.getByLabelText(
        /allow playlist downloads/i,
      ) as HTMLInputElement;
      expect(cb.checked).toBe(true);
    });
  });

  it("clipboard prefill does NOT set allowPlaylist for regular video URL", async () => {
    clipReadMock.mockImplementation(
      async () => "https://youtube.com/watch?v=abc",
    );
    render(<GenericYtdlpDownloader />);
    // Give effect a tick to run
    await new Promise((r) => setTimeout(r, 10));
    const cb = screen.getByLabelText(
      /allow playlist downloads/i,
    ) as HTMLInputElement;
    expect(cb.checked).toBe(false);
  });

  it("typing a playlist URL auto-enables allowPlaylist", async () => {
    render(<GenericYtdlpDownloader />);
    const urlInput = screen.getByPlaceholderText(/https:\/\/\.\.\./);
    fireEvent.change(urlInput, {
      target: { value: "https://soundcloud.com/user/sets/my-set" },
    });
    const cb = screen.getByLabelText(
      /allow playlist downloads/i,
    ) as HTMLInputElement;
    expect(cb.checked).toBe(true);
  });

  it("start button label reflects playlist detection", async () => {
    render(<GenericYtdlpDownloader />);
    // Set outDir so button becomes enabled
    fireEvent.click(screen.getByRole("button", { name: /^pick$/i }));
    await waitFor(() => {
      // With no URL, button says "Fetch metadata"
      expect(
        screen.getByRole("button", { name: /fetch metadata/i }),
      ).toBeInTheDocument();
    });

    // Type a playlist URL
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/\.\.\./), {
      target: { value: "https://youtube.com/playlist?list=PLxyz" },
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /fetch playlist metadata/i }),
      ).toBeInTheDocument();
    });
  });
});

// ─────────────────────────────────────────────────────────────
// Playlist selection
// ─────────────────────────────────────────────────────────────

const playlistMetadataMsg = {
  type: "metadata",
  title: "My Playlist",
  is_playlist: true,
  playlist_count: 5,
  playlist_preview_cap: 100,
  playlist_preview: [
    { index: 1, title: "Track 1" },
    { index: 2, title: "Track 2" },
    { index: 3, title: "Track 3" },
    { index: 4, title: "Track 4" },
    { index: 5, title: "Track 5" },
  ],
};

async function startAndDeliverPlaylistMetadata() {
  render(<GenericYtdlpDownloader />);
  fireEvent.change(screen.getByPlaceholderText(/https:\/\/\.\.\./), {
    target: { value: "https://youtube.com/playlist?list=PLxyz" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^pick$/i }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /fetch playlist metadata/i }),
    ).not.toBeDisabled(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: /fetch playlist metadata/i }),
  );

  await act(async () => {
    emitStreamLine(playlistMetadataMsg);
  });
}

describe("GenericYtdlpDownloader — playlist selection", () => {
  it("selects all items by default when playlist metadata arrives", async () => {
    await startAndDeliverPlaylistMetadata();
    // Selected 5 / 5
    expect(screen.getByText(/selected 5 \/ 5/i)).toBeInTheDocument();
  });

  it("Select none clears all selections", async () => {
    await startAndDeliverPlaylistMetadata();
    fireEvent.click(screen.getByRole("button", { name: /^select none$/i }));
    expect(screen.getByText(/selected 0 \/ 5/i)).toBeInTheDocument();
  });

  it("Invert toggles selection state per item", async () => {
    await startAndDeliverPlaylistMetadata();
    // Start with all selected. Select none first, then select item 1, then invert.
    fireEvent.click(screen.getByRole("button", { name: /^select none$/i }));

    // Click checkbox for item 1
    const checkboxes = screen.getAllByRole("checkbox");
    // Find the checkbox for the playlist row with index 1
    // There are also other checkboxes on the page (allow-playlist, etc.).
    // Playlist row checkboxes come after the config checkboxes; find by the label parent.
    const item1Row = screen.getByText("Track 1").closest("label");
    const item1Checkbox = item1Row?.querySelector(
      'input[type="checkbox"]',
    ) as HTMLInputElement;
    fireEvent.click(item1Checkbox);
    expect(screen.getByText(/selected 1 \/ 5/i)).toBeInTheDocument();

    // Invert -> should select 2,3,4,5 (deselect 1)
    fireEvent.click(screen.getByRole("button", { name: /^invert$/i }));
    expect(screen.getByText(/selected 4 \/ 5/i)).toBeInTheDocument();
  });

  it("Confirm button disabled when 0 items selected", async () => {
    await startAndDeliverPlaylistMetadata();
    fireEvent.click(screen.getByRole("button", { name: /^select none$/i }));
    const confirmBtn = screen.getByRole("button", {
      name: /confirm & download selected/i,
    });
    expect(confirmBtn).toBeDisabled();
  });

  it("Confirm sends compacted range string as playlist_items", async () => {
    await startAndDeliverPlaylistMetadata();
    // Select none, then select 1, 2, 4
    fireEvent.click(screen.getByRole("button", { name: /^select none$/i }));
    fireEvent.click(
      screen
        .getByText("Track 1")
        .closest("label")!
        .querySelector('input[type="checkbox"]')!,
    );
    fireEvent.click(
      screen
        .getByText("Track 2")
        .closest("label")!
        .querySelector('input[type="checkbox"]')!,
    );
    fireEvent.click(
      screen
        .getByText("Track 4")
        .closest("label")!
        .querySelector('input[type="checkbox"]')!,
    );
    expect(screen.getByText(/selected 3 \/ 5/i)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /confirm & download selected/i }),
    );

    await waitFor(() => {
      const log = getStreamInputLog();
      expect(log.length).toBeGreaterThan(0);
      const last = log[log.length - 1] as any;
      expect(last.action).toBe("confirm");
      expect(last.allow_playlist).toBe(true);
      expect(last.playlist_items).toBe("1-2,4");
    });
  });
});
