import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { createRef } from "react";
import BookmarkEditor from "../src/features/BookmarkEditor.jsx";

// The BookmarkEditor pulls PickFile, RunScript, AnalyzeBookmarks off
// window.electronAPI at module load. Our harness installs a fresh mock
// per test, but this component captured the references at import time,
// so we need to redirect the captured refs before each test.
//
// We do this by re-installing the mock and then replacing the specific
// methods with fresh spies we can inspect per test.
// BookmarkEditor captures window.electronAPI methods at module load, so we
// cannot swap them out here. Instead we grab the same references the module
// captured and reset their behavior each test via mockImplementation.
// @ts-expect-error
const pickFileMock = window.electronAPI.PickFile as ReturnType<typeof vi.fn>;
// @ts-expect-error
const runScriptMock = window.electronAPI.RunScript as ReturnType<typeof vi.fn>;
// @ts-expect-error
const analyzeBookmarksMock = window.electronAPI.AnalyzeBookmarks as ReturnType<
  typeof vi.fn
>;

beforeEach(() => {
  pickFileMock.mockReset();
  runScriptMock.mockReset();
  analyzeBookmarksMock.mockReset();

  pickFileMock.mockImplementation(async () => "/mock/doc.pdf");
  runScriptMock.mockImplementation(async () => ({ output: "ok" }));
  analyzeBookmarksMock.mockImplementation(async () => ({
    info: "3 chapters detected",
    entries: [
      [1, "Introduction"],
      [12, "Chapter 1"],
      [45, "Chapter 2"],
    ],
  }));
});

const registryGroups = [
  {
    name: "Documents",
    scripts: [
      { name: "PDF → Text", operation: "pdf_to_txt" },
      { name: "PDF Bookmarks", operation: "pdf_bookmark_add" },
    ],
  },
];

describe("BookmarkEditor", () => {
  it("initial state shows picker, hides textarea", () => {
    render(<BookmarkEditor groups={registryGroups} />);
    expect(screen.getByText(/PDF file/i)).toBeInTheDocument();
    // Textarea only appears after analyze
    expect(document.querySelector("textarea.bookmark-textarea")).toBeNull();
  });

  it("picking a PDF stores path and enables Analyze button", async () => {
    render(<BookmarkEditor groups={registryGroups} />);
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled();
    });
  });

  it("successful analyze switches to textarea view with formatted entries", async () => {
    render(<BookmarkEditor groups={registryGroups} />);
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() => {
      const textarea = document.querySelector(
        "textarea.bookmark-textarea",
      ) as HTMLTextAreaElement;
      expect(textarea).toBeInTheDocument();
      expect(textarea.value).toContain("1:Introduction");
      expect(textarea.value).toContain("12:Chapter 1");
      expect(textarea.value).toContain("45:Chapter 2");
      expect(textarea.value).toContain("# 3 chapters detected");
    });
  });

  it("failed analyze surfaces error in info, does not switch views", async () => {
    analyzeBookmarksMock.mockRejectedValueOnce(new Error("PDF corrupt"));
    render(<BookmarkEditor groups={registryGroups} />);
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/Analysis failed: PDF corrupt/),
      ).toBeInTheDocument();
    });
    // Still on picker view
    expect(document.querySelector("textarea.bookmark-textarea")).toBeNull();
  });

  it("editing text calls onCanApplyChange with true for non-empty, false for empty", async () => {
    const onCanApplyChange = vi.fn();
    render(
      <BookmarkEditor
        groups={registryGroups}
        onCanApplyChange={onCanApplyChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() => {
      expect(
        document.querySelector("textarea.bookmark-textarea"),
      ).toBeInTheDocument();
    });
    onCanApplyChange.mockClear();
    const textarea = document.querySelector(
      "textarea.bookmark-textarea",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "1:Intro" } });
    expect(onCanApplyChange).toHaveBeenLastCalledWith(true);
    fireEvent.change(textarea, { target: { value: "" } });
    expect(onCanApplyChange).toHaveBeenLastCalledWith(false);
  });

  it("apply() via ref calls RunScript with correct indices for pdf_bookmark_add", async () => {
    const ref = createRef<any>();
    render(<BookmarkEditor ref={ref} groups={registryGroups} />);
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() =>
      expect(
        document.querySelector("textarea.bookmark-textarea"),
      ).toBeInTheDocument(),
    );

    await act(async () => {
      await ref.current!.apply();
    });

    expect(runScriptMock).toHaveBeenCalledTimes(1);
    const [groupIdx, scriptIdx, args] = runScriptMock.mock.calls[0];
    expect(groupIdx).toBe(0);
    expect(scriptIdx).toBe(1); // pdf_bookmark_add is second entry
    expect(args[0]).toBe("/mock/doc.pdf");
    expect(args[1]).toBe("--pdf_bookmark_add-list");
    expect(args[2]).toContain("1:Introduction");
  });

  it("apply() reports error status when pdf_bookmark_add entry missing from registry", async () => {
    const onStatusChange = vi.fn();
    const onOutput = vi.fn();
    const ref = createRef<any>();
    const brokenGroups = [
      {
        name: "Documents",
        scripts: [{ name: "PDF → Text", operation: "pdf_to_txt" }],
      },
    ];
    render(
      <BookmarkEditor
        ref={ref}
        groups={brokenGroups}
        onStatusChange={onStatusChange}
        onOutput={onOutput}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() =>
      expect(
        document.querySelector("textarea.bookmark-textarea"),
      ).toBeInTheDocument(),
    );

    await act(async () => {
      await ref.current!.apply();
    });

    expect(onStatusChange).toHaveBeenCalledWith("error");
    expect(onOutput).toHaveBeenCalledWith(
      expect.stringContaining("pdf_bookmark_add entry missing"),
    );
    expect(runScriptMock).not.toHaveBeenCalled();
  });

  it("reset() clears path, text, and disables apply", async () => {
    const onCanApplyChange = vi.fn();
    const ref = createRef<any>();
    render(
      <BookmarkEditor
        ref={ref}
        groups={registryGroups}
        onCanApplyChange={onCanApplyChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /pick pdf/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /analyze$/i }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /analyze$/i }));
    await waitFor(() =>
      expect(
        document.querySelector("textarea.bookmark-textarea"),
      ).toBeInTheDocument(),
    );

    onCanApplyChange.mockClear();
    act(() => {
      ref.current!.reset();
    });

    // Back to picker view
    expect(document.querySelector("textarea.bookmark-textarea")).toBeNull();
    expect(screen.getByText(/PDF file/i)).toBeInTheDocument();
    expect(onCanApplyChange).toHaveBeenLastCalledWith(false);
  });
});
