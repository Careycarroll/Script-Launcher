import { useState, useEffect } from "react";
const {
  VaultStart,
  VaultQuery,
  VaultStop,
  PickFolder,
  GetGroups,
  RunScript,
  PtyCreate,
} = window.electronAPI;

const STORAGE_KEY = "vault-workbench-path";
const DEFAULT_VAULT_PATH =
  "/Users/careycarroll/Library/Mobile Documents/iCloud~md~obsidian/Documents/CAWC Vaulting";

// Monotonically increasing request id for JSON protocol matching.
let reqCounter = 0;
const nextId = () => `r${++reqCounter}`;

export default function VaultWorkbench() {
  const [vaultPath, setVaultPath] = useState(
    () => localStorage.getItem(STORAGE_KEY) || DEFAULT_VAULT_PATH,
  );
  const [status, setStatus] = useState("stopped"); // stopped | starting | running | error
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null);
  const [hubs, setHubs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [alsoInDomain, setAlsoInDomain] = useState([]);

  // Load registry entries for the vault domain (for the "Also in Vault" list).
  useEffect(() => {
    GetGroups().then((groups) => {
      const flat = [];
      groups.forEach((group, gi) => {
        (group.scripts || []).forEach((s, si) => {
          const d = s.domain || "documents";
          // Skip self-referential Vault Workbench entries if any.
          if (d === "vault" && s.component !== "VaultWorkbench") {
            flat.push({ ...s, groupIdx: gi, scriptIdx: si });
          }
        });
      });
      setAlsoInDomain(flat);
    });
  }, []);

  // Persist vault path.
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, vaultPath);
  }, [vaultPath]);

  // Kill server on unmount.
  useEffect(
    () => () => {
      VaultStop();
    },
    [],
  );

  async function pickPath() {
    const p = await PickFolder();
    if (p) setVaultPath(p);
  }

  async function start() {
    if (!vaultPath) return;
    setBusy(true);
    setStatus("starting");
    setError("");
    try {
      await VaultStart(vaultPath);
      setStatus("running");
    } catch (e) {
      setStatus("error");
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await VaultStop();
    } catch {
      /* ignore */
    }
    setStatus("stopped");
    setSummary(null);
    setHubs([]);
    setBusy(false);
  }

  async function reindex() {
    if (status !== "running") return;
    setBusy(true);
    setError("");
    try {
      const reindexRes = await VaultQuery({
        id: nextId(),
        method: "reindex",
        params: {},
      });
      setSummary(reindexRes);
      // Follow up with get_index to grab hubs (reindex only returns summary counts).
      const idx = await VaultQuery({
        id: nextId(),
        method: "get_index",
        params: {},
      });
      setHubs(idx.hubs || []);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function runAlsoInDomain(entry) {
    if (entry.interactive) {
      window.location.hash = "#/terminal";
      await PtyCreate(entry.path, []);
    } else {
      const result = await RunScript(entry.groupIdx, entry.scriptIdx, []);
      alert(result.output || result.error || "(no output)");
    }
  }

  const statusDot = {
    stopped: "●",
    starting: "⟳",
    running: "●",
    error: "✗",
  }[status];
  const statusColor = {
    stopped: "var(--text-muted)",
    starting: "var(--tokyo-orange)",
    running: "var(--tokyo-green)",
    error: "var(--tokyo-red)",
  }[status];

  return (
    <div className="vault-workbench">
      <div className="vault-header">
        <div className="vault-path-row">
          <span className="vault-path-label">Vault:</span>
          <span className="vault-path" title={vaultPath}>
            {vaultPath}
          </span>
          <button
            className="btn-secondary"
            onClick={pickPath}
            disabled={status !== "stopped"}
          >
            Change
          </button>
        </div>
        <div className="vault-status-row">
          <span className="vault-status" style={{ color: statusColor }}>
            {statusDot} {status}
          </span>
          {status === "stopped" && (
            <button
              className="btn-run"
              onClick={start}
              disabled={busy || !vaultPath}
            >
              Start
            </button>
          )}
          {status === "running" && (
            <>
              <button className="btn-run" onClick={reindex} disabled={busy}>
                {busy ? "Working…" : "Reindex"}
              </button>
              <button className="btn-secondary" onClick={stop} disabled={busy}>
                Stop
              </button>
            </>
          )}
        </div>
        {error && <div className="vault-error">{error}</div>}
      </div>

      <div className="vault-body">
        {!summary && status !== "running" && (
          <div className="empty-state">
            Click Start, then Reindex to build the vault index.
          </div>
        )}
        {!summary && status === "running" && (
          <div className="empty-state">
            Server started. Click Reindex to build the vault index.
          </div>
        )}
        {summary && (
          <div className="vault-metrics">
            <div className="vault-metric-row">
              <span className="vault-metric-value">{summary.note_count}</span>{" "}
              notes
            </div>
            <div className="vault-metric-row">
              <span className="vault-metric-value">{summary.edge_count}</span>{" "}
              edges
            </div>
            <div className="vault-metric-row">
              <span className="vault-metric-value">
                {summary.broken_link_count}
              </span>{" "}
              broken links
            </div>
            <div className="vault-metric-row">
              <span className="vault-metric-value">{summary.orphan_count}</span>{" "}
              orphans
            </div>
            <div className="vault-metric-row">
              <span className="vault-metric-value">
                {summary.component_count}
              </span>{" "}
              components
            </div>
            {hubs.length > 0 && (
              <>
                <div className="vault-metrics-heading">Top hubs</div>
                <div className="vault-hubs">
                  {hubs.slice(0, 10).map((h) => (
                    <div key={h.title} className="vault-hub-row">
                      <span className="vault-hub-degree">{h.in_degree}</span>
                      <span className="vault-hub-title">{h.title}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {alsoInDomain.length > 0 && (
        <div className="vault-also">
          <div className="vault-also-heading">Also in Vault</div>
          <div className="vault-also-list">
            {alsoInDomain.map((entry) => (
              <button
                key={entry.name}
                className="btn-secondary"
                onClick={() => runAlsoInDomain(entry)}
              >
                {entry.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
