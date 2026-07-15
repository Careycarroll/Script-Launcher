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
  return (
    <section className="vault-domain-panel">
      <div className="vault-domain-card">
        <div className="script-name">Book Notes</div>
        <div className="script-desc">
          Chapter-note generation for Obsidian book notes is coming in v0.6.
        </div>
        <div className="help-box">
          <strong>Coming soon</strong>
          This tab is reserved for issue #77. The current refactor only creates
          the peer location where the Book Notes workflow will land.
        </div>
      </div>
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
