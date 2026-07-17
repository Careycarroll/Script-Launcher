import { useEffect, useMemo, useState } from "react";
import TerminalPanel from "../Terminal";
import VaultWorkbench from "./VaultWorkbench";

const TABS = [
  { id: "manage", label: "Manage Vault" },
  { id: "health", label: "Vault Health" },
  { id: "workbench", label: "Vault Workbench" },
  { id: "book-notes", label: "Book Notes" },
];

function findVaultScript(groups, name) {
  for (const group of groups || []) {
    for (const script of group.scripts || []) {
      const domain = script.domain || "documents";
      if (domain === "vault" && script.name === name) return script;
    }
  }
  return null;
}

function VaultLaunchPanel({ scriptName, title, description }) {
  const [script, setScript] = useState(null);
  const [loading, setLoading] = useState(true);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalReady, setTerminalReady] = useState(false);
  const [pendingLaunch, setPendingLaunch] = useState(false);

  useEffect(() => {
    let alive = true;
    window.electronAPI
      .GetGroups()
      .then((groups) => {
        if (!alive) return;
        setScript(findVaultScript(groups, scriptName));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [scriptName]);

  useEffect(() => {
    if (!terminalReady || !pendingLaunch || !script) return;
    const launch = async () => {
      await window.electronAPI.PtyCreate(script.path, []);
      setPendingLaunch(false);
    };
    launch();
  }, [terminalReady, pendingLaunch, script]);

  async function launchScript() {
    if (!script) return;
    setTerminalOpen(true);
    setTerminalReady(false);
    setPendingLaunch(true);
  }

  async function closeTerminal() {
    await window.electronAPI.PtyKill();
    setTerminalOpen(false);
    setTerminalReady(false);
    setPendingLaunch(false);
  }

  return (
    <section className="vault-domain-panel">
      <div className="vault-domain-card">
        <div>
          <div className="script-name">{title}</div>
          <div className="script-desc">{description}</div>
        </div>
        <div className="vault-domain-actions">
          <button
            className="btn-primary"
            onClick={launchScript}
            disabled={loading || !script}
          >
            {loading ? "Loading…" : `Launch ${scriptName}`}
          </button>
          {terminalOpen && (
            <button className="btn-secondary" onClick={closeTerminal}>
              Close Terminal
            </button>
          )}
        </div>
        {!loading && !script && (
          <div className="help-box">
            <strong>Unavailable</strong>
            Could not find the {scriptName} registry entry.
          </div>
        )}
      </div>

      {terminalOpen && (
        <div className="vault-domain-terminal" data-testid="vault-terminal">
          <TerminalPanel
            autoStartShell={false}
            onReady={() => setTerminalReady(true)}
          />
        </div>
      )}
    </section>
  );
}

function BookNotesPanel() {
  const [baseNote, setBaseNote] = useState("");
  const [dest, setDest] = useState("");
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [chapterMode, setChapterMode] = useState("count");
  const [chapterCount, setChapterCount] = useState("12");
  const [chapters, setChapters] = useState("");
  const [error, setError] = useState("");
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalReady, setTerminalReady] = useState(false);
  const [pendingArgs, setPendingArgs] = useState(null);

  useEffect(() => {
    if (!terminalReady || !pendingArgs) return;
    const launch = async () => {
      await window.electronAPI.PtyCreate("python/scripts/book_notes.py", pendingArgs);
      setPendingArgs(null);
    };
    launch();
  }, [terminalReady, pendingArgs]);

  async function pickBaseNote() {
    const picked = await window.electronAPI.PickFile(["md"]);
    if (picked) setBaseNote(picked);
  }

  async function pickDest() {
    const picked = await window.electronAPI.PickFolder();
    if (picked) setDest(picked);
  }

  function buildArgs() {
    const args = ["create", "--base-note", baseNote];

    if (dest.trim()) args.push("--dest", dest.trim());
    if (title.trim()) args.push("--title", title.trim());
    if (author.trim()) args.push("--author", author.trim());

    if (chapterMode === "count") {
      args.push("--chapter-count", String(chapterCount || "0"));
    } else {
      args.push("--chapters", chapters);
    }

    return args;
  }

  async function createWorkspace() {
    setError("");

    if (!baseNote.trim()) {
      setError("Pick a base Obsidian book note first.");
      return;
    }

    if (chapterMode === "count") {
      const n = Number(chapterCount);
      if (!Number.isInteger(n) || n <= 0) {
        setError("Chapter count must be a positive whole number.");
        return;
      }
    } else if (!chapters.trim()) {
      setError("Paste at least one chapter title.");
      return;
    }

    setTerminalOpen(true);
    setTerminalReady(false);
    setPendingArgs(buildArgs());
  }

  async function closeTerminal() {
    await window.electronAPI.PtyKill();
    setTerminalOpen(false);
    setTerminalReady(false);
    setPendingArgs(null);
  }

  return (
    <section className="vault-domain-panel">
      <div className="vault-domain-card">
        <div className="script-name">Book Notes</div>
        <div className="script-desc">
          Scaffold all chapter notes for a book at once, then fill them
          chapter-by-chapter with your external AI workflow.
        </div>
        <div className="help-box">
          <strong>Workflow</strong>
          Use PDF Bookmarks and PDF Split first if needed. This tool only
          creates the Obsidian note structure and AI handoff files; it does not
          split books, call AI, or generate chapter content.
        </div>

        <div className="book-notes-form">
          <div className="arg-group">
            <label className="arg-label" htmlFor="book-base-note">
              Base book note
            </label>
            <div className="arg-row">
              <input
                id="book-base-note"
                className="arg-input"
                value={baseNote}
                onChange={(e) => setBaseNote(e.target.value)}
                placeholder="Pick an existing Obsidian .md book note"
              />
              <button className="btn-pick" onClick={pickBaseNote}>
                Pick Note
              </button>
            </div>
          </div>

          <div className="arg-group">
            <label className="arg-label" htmlFor="book-dest">
              Destination folder
            </label>
            <div className="arg-row">
              <input
                id="book-dest"
                className="arg-input"
                value={dest}
                onChange={(e) => setDest(e.target.value)}
                placeholder="Default: ~/Documents/Vault Management/{book-slug}"
              />
              <button className="btn-pick" onClick={pickDest}>
                Pick Folder
              </button>
            </div>
          </div>

          <div className="arg-row">
            <div className="arg-group" style={{ flex: 1 }}>
              <label className="arg-label" htmlFor="book-title">
                Book title override
              </label>
              <input
                id="book-title"
                className="arg-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div className="arg-group" style={{ flex: 1 }}>
              <label className="arg-label" htmlFor="book-author">
                Author override
              </label>
              <input
                id="book-author"
                className="arg-input"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="arg-group">
            <div className="arg-label">Chapter setup</div>
            <div className="book-notes-mode">
              <label>
                <input
                  type="radio"
                  checked={chapterMode === "count"}
                  onChange={() => setChapterMode("count")}
                />
                Chapter count
              </label>
              <label>
                <input
                  type="radio"
                  checked={chapterMode === "list"}
                  onChange={() => setChapterMode("list")}
                />
                Pasted chapter list
              </label>
            </div>
          </div>

          {chapterMode === "count" ? (
            <div className="arg-group">
              <label className="arg-label" htmlFor="chapter-count">
                Chapter count
              </label>
              <input
                id="chapter-count"
                className="arg-input"
                type="number"
                min="1"
                value={chapterCount}
                onChange={(e) => setChapterCount(e.target.value)}
              />
            </div>
          ) : (
            <div className="arg-group">
              <label className="arg-label" htmlFor="chapter-list">
                Chapter titles
              </label>
              <textarea
                id="chapter-list"
                className="arg-input"
                rows={8}
                value={chapters}
                onChange={(e) => setChapters(e.target.value)}
                placeholder={"Introduction\nThe Big Idea\nApplications"}
              />
            </div>
          )}

          {error && <div className="error-text">{error}</div>}

          <div className="vault-domain-actions">
            <button className="btn-primary" onClick={createWorkspace}>
              Create Workspace
            </button>
            {terminalOpen && (
              <button className="btn-secondary" onClick={closeTerminal}>
                Close Terminal
              </button>
            )}
          </div>
        </div>
      </div>

      {terminalOpen && (
        <div className="vault-domain-terminal" data-testid="book-notes-terminal">
          <TerminalPanel
            autoStartShell={false}
            onReady={() => setTerminalReady(true)}
          />
        </div>
      )}
    </section>
  );
}

export default function VaultDomain() {
  const [activeTab, setActiveTab] = useState("manage");

  const activeLabel = useMemo(
    () => TABS.find((tab) => tab.id === activeTab)?.label || "Vault",
    [activeTab],
  );

  return (
    <div className="vault-domain">
      <div className="vault-domain-header">
        <div>
          <h1>Vault</h1>
          <p>Manage, inspect, and analyze your Obsidian vault.</p>
        </div>
      </div>

      <div className="vault-domain-tabs" role="tablist" aria-label="Vault tools">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`vault-domain-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <main className="vault-domain-body" role="tabpanel" aria-label={activeLabel}>
        {activeTab === "manage" && (
          <VaultLaunchPanel
            scriptName="Manage Vault"
            title="Manage Vault"
            description="Launch the interactive vault management TUI inside Heelworks."
          />
        )}

        {activeTab === "health" && (
          <VaultLaunchPanel
            scriptName="Vault Health"
            title="Vault Health"
            description="Run the vault health scanner in an embedded terminal."
          />
        )}

        {activeTab === "workbench" && <VaultWorkbench />}

        {activeTab === "book-notes" && <BookNotesPanel />}
      </main>
    </div>
  );
}
