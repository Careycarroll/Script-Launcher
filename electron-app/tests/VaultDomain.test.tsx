import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../src/tiles/VaultWorkbench.jsx", () => ({
  default: () => <div>Mock Vault Workbench</div>,
}));

vi.mock("../src/Terminal.jsx", async () => {
  const React = await import("react");
  return {
    default: ({ onReady }: { onReady?: () => void }) => {
      React.useEffect(() => {
        onReady?.();
      }, [onReady]);
      return <div>Mock Terminal</div>;
    },
  };
});

import VaultDomain from "../src/tiles/VaultDomain.jsx";

const groups = [
  {
    name: "Vault",
    scripts: [
      {
        name: "Manage Vault",
        domain: "vault",
        path: "/Users/careycarroll/bin/manage_vault",
        interactive: true,
      },
      {
        name: "Vault Health",
        domain: "vault",
        path: "/Users/careycarroll/bin/vault_health",
        interactive: false,
      },
    ],
  },
];

beforeEach(() => {
  window.electronAPI.GetGroups = vi.fn(async () => groups);
  window.electronAPI.PickFile = vi.fn(async () => "/mock/vault/_Example Book.md");
  window.electronAPI.PickFolder = vi.fn(async () => "/mock/vault/Example Book");
  window.electronAPI.PtyCreate = vi.fn(async () => true);
  window.electronAPI.PtyKill = vi.fn(async () => true);
});

describe("VaultDomain", () => {
  it("renders the four Vault peer tabs", () => {
    render(<VaultDomain />);

    expect(screen.getByRole("tab", { name: "Manage Vault" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Vault Health" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Vault Workbench" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Book Notes" })).toBeInTheDocument();
  });

  it("defaults to the Manage Vault panel", async () => {
    render(<VaultDomain />);

    expect(await screen.findByText(/interactive vault management/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Manage Vault" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches to Vault Health", async () => {
    render(<VaultDomain />);

    fireEvent.click(screen.getByRole("tab", { name: "Vault Health" }));

    expect(await screen.findByText(/vault health scanner/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Vault Health" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches to Vault Workbench", () => {
    render(<VaultDomain />);

    fireEvent.click(screen.getByRole("tab", { name: "Vault Workbench" }));

    expect(screen.getByText("Mock Vault Workbench")).toBeInTheDocument();
  });

  it("switches to Book Notes form", () => {
    render(<VaultDomain />);

    fireEvent.click(screen.getByRole("tab", { name: "Book Notes" }));

    expect(screen.getAllByText("Book Notes").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Scaffold all chapter notes/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create Workspace/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pick Note/i })).toBeInTheDocument();
  });

  it("picks a base note and launches Book Notes create command", async () => {
    render(<VaultDomain />);

    fireEvent.click(screen.getByRole("tab", { name: "Book Notes" }));
    fireEvent.click(screen.getByRole("button", { name: /Pick Note/i }));
    await waitFor(() =>
      expect(screen.getByDisplayValue("/mock/vault/_Example Book.md")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Create Workspace/i }));

    expect(await screen.findByText("Mock Terminal")).toBeInTheDocument();
    expect(window.electronAPI.PtyCreate).toHaveBeenCalledWith(
      "python/scripts/book_notes.py",
      [
        "create",
        "--base-note",
        "/mock/vault/_Example Book.md",
        "--chapter-count",
        "12",
      ],
    );
  });

  it("passes pasted chapter titles to Book Notes create command", async () => {
    render(<VaultDomain />);

    fireEvent.click(screen.getByRole("tab", { name: "Book Notes" }));
    fireEvent.click(screen.getByRole("button", { name: /Pick Note/i }));
    await waitFor(() =>
      expect(screen.getByDisplayValue("/mock/vault/_Example Book.md")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByLabelText(/Pasted chapter list/i));
    fireEvent.change(screen.getByLabelText(/Chapter titles/i), {
      target: { value: "Introduction\nThe Big Idea" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create Workspace/i }));

    expect(await screen.findByText("Mock Terminal")).toBeInTheDocument();
    expect(window.electronAPI.PtyCreate).toHaveBeenCalledWith(
      "python/scripts/book_notes.py",
      [
        "create",
        "--base-note",
        "/mock/vault/_Example Book.md",
        "--chapters",
        "Introduction\nThe Big Idea",
      ],
    );
  });

  it("launches Manage Vault through the embedded terminal path", async () => {
    render(<VaultDomain />);

    const launch = await screen.findByRole("button", { name: /Launch Manage Vault/i });
    fireEvent.click(launch);

    expect(await screen.findByText("Mock Terminal")).toBeInTheDocument();
    expect(window.electronAPI.PtyCreate).toHaveBeenCalledWith(
      "/Users/careycarroll/bin/manage_vault",
      [],
    );
  });
});
