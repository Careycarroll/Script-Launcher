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

let reqCounter = 0;
const nextId = () => `r${++reqCounter}`;

const TABS = [
  "Overview",
  "Orphans",
  "Broken Links",
  "Tags",
  "Duplicates",
  "Components",
];

export default function VaultWorkbench() {
  const [vaultPath, setVaultPath] = useState(
    () => localStorage.getItem(STORAGE_KEY) || DEFAULT_VAULT_PATH,
  );
  const [status, setStatus] = useState("stopped");
  const [error, setError] = useState("");
  const [index, setIndex] = useState(null); // full get_index result
  const [busy, setBusy] = useState(false);
  const [alsoInDomain, setAlsoInDomain] = useState([]);
  const [activeTab, setActiveTab] = useState("Overview");

  useEffect(() => {
    GetGroups().then((groups) => {
      const flat = [];
      groups.forEach((group, gi) => {
        (group.scripts || []).forEach((s, si) => {
          const d = s.domain || "documents";
          if (d === "vault" && s.component !== "VaultWorkbench") {
            flat.push({ ...s, groupIdx: gi, scriptIdx: si });
          }
        });
      });
      setAlsoInDomain(flat);
    });
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, vaultPath);
  }, [vaultPath]);

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
    setIndex(null);
    setBusy(false);
  }

  async function reindex() {
    if (status !== "running") return;
    setBusy(true);
    setError("");
    try {
      await VaultQuery({ id: nextId(), method: "reindex", params: {} });
      const idx = await VaultQuery({
        id: nextId(),
        method: "get_index",
        params: {},
      });
      setIndex(idx);
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

  const statusDot = { stopped: "●", starting: "⟳", running: "●", error: "✗" }[
    status
  ];
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

      {!index && status !== "running" && (
        <div className="vault-empty">
          Click Start, then Reindex to build the vault index.
        </div>
      )}
      {!index && status === "running" && (
        <div className="vault-empty">
          Server started. Click Reindex to build the vault index.
        </div>
      )}

      {index && (
        <>
          <div className="vault-tabs">
            {TABS.map((tab) => (
              <button
                key={tab}
                className={`vault-tab ${activeTab === tab ? "active" : ""}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab}
                <span className="vault-tab-count">{tabCount(tab, index)}</span>
              </button>
            ))}
          </div>

          <div className="vault-tab-body">
            {activeTab === "Overview" && <OverviewTab index={index} />}
            {activeTab === "Orphans" && <OrphansTab index={index} />}
            {activeTab === "Broken Links" && <BrokenLinksTab index={index} />}
            {activeTab === "Tags" && <TagsTab index={index} />}
            {activeTab === "Duplicates" && <DuplicatesTab index={index} />}
            {activeTab === "Components" && <ComponentsTab index={index} />}
          </div>
        </>
      )}

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

function tabCount(tab, idx) {
  switch (tab) {
    case "Overview":
      return idx.note_count;
    case "Orphans":
      return idx.orphans.length;
    case "Broken Links":
      return idx.broken_links.length;
    case "Tags":
      return Object.keys(idx.tag_counts).length;
    case "Duplicates":
      return idx.duplicate_titles.length;
    case "Components":
      return idx.components.length;
    default:
      return "";
  }
}

// ── Tabs ────────────────────────────────────────────────────────────────────
function OverviewTab({ index }) {
  return (
    <div className="vault-metrics">
      <div className="vault-metric-row">
        <span className="vault-metric-value">{index.note_count}</span> notes
      </div>
      <div className="vault-metric-row">
        <span className="vault-metric-value">{index.edges.length}</span> edges
      </div>
      <div className="vault-metric-row">
        <span className="vault-metric-value">{index.broken_links.length}</span>{" "}
        broken links
      </div>
      <div className="vault-metric-row">
        <span className="vault-metric-value">{index.orphans.length}</span>{" "}
        orphans
      </div>
      <div className="vault-metric-row">
        <span className="vault-metric-value">{index.components.length}</span>{" "}
        components
      </div>
      {index.hubs.length > 0 && (
        <>
          <div className="vault-metrics-heading">Top hubs</div>
          <div className="vault-hubs">
            {index.hubs.slice(0, 15).map((h) => (
              <div key={h.title} className="vault-hub-row">
                <span className="vault-hub-degree">{h.in_degree}</span>
                <span className="vault-hub-title">{h.title}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function OrphansTab({ index }) {
  const [query, setQuery] = useState("");
  const filtered = index.orphans.filter(
    (t) => !query || t.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="vault-list-panel">
      <div className="vault-list-toolbar">
        <input
          className="vault-list-filter"
          placeholder="Filter orphans…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="vault-list-count">
          {filtered.length} / {index.orphans.length}
        </span>
      </div>
      <div className="vault-list">
        {filtered.map((title) => (
          <div key={title} className="vault-list-row">
            <span className="vault-list-title">{title}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="vault-list-empty">No orphans match your filter.</div>
        )}
      </div>
    </div>
  );
}

function BrokenLinksTab({ index }) {
  const [query, setQuery] = useState("");
  const filtered = index.broken_links.filter(
    (l) =>
      !query ||
      l.source.toLowerCase().includes(query.toLowerCase()) ||
      l.target.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="vault-list-panel">
      <div className="vault-list-toolbar">
        <input
          className="vault-list-filter"
          placeholder="Filter broken links…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="vault-list-count">
          {filtered.length} / {index.broken_links.length}
        </span>
      </div>
      <div className="vault-list">
        {filtered.map((l, i) => (
          <div key={i} className="vault-list-row vault-link-row">
            <span className="vault-link-source">{l.source}</span>
            <span className="vault-link-arrow">→</span>
            <span className="vault-link-target">{l.target}</span>
            <span className="vault-link-type">{l.type}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="vault-list-empty">
            No broken links match your filter.
          </div>
        )}
      </div>
    </div>
  );
}

function TagsTab({ index }) {
  const [query, setQuery] = useState("");
  const entries = Object.entries(index.tag_counts);
  const filtered = entries.filter(
    ([tag]) => !query || tag.toLowerCase().includes(query.toLowerCase()),
  );
  const maxCount = Math.max(...entries.map(([, c]) => c), 1);
  return (
    <div className="vault-list-panel">
      <div className="vault-list-toolbar">
        <input
          className="vault-list-filter"
          placeholder="Filter tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="vault-list-count">
          {filtered.length} / {entries.length}
        </span>
      </div>
      <div className="vault-list">
        {filtered.map(([tag, count]) => (
          <div key={tag} className="vault-list-row vault-tag-row">
            <span className="vault-tag-name">{tag}</span>
            <div className="vault-tag-bar-wrap">
              <div
                className="vault-tag-bar"
                style={{ width: `${(count / maxCount) * 100}%` }}
              />
            </div>
            <span className="vault-tag-count">{count}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="vault-list-empty">No tags match your filter.</div>
        )}
      </div>
    </div>
  );
}

function DuplicatesTab({ index }) {
  return (
    <div className="vault-list-panel">
      <div className="vault-list">
        {index.duplicate_titles.map((dup, i) => (
          <div key={i} className="vault-dup-block">
            <div className="vault-dup-title">{dup.title}</div>
            {dup.paths.map((p) => (
              <div key={p} className="vault-dup-path">
                {p}
              </div>
            ))}
          </div>
        ))}
        {index.duplicate_titles.length === 0 && (
          <div className="vault-list-empty">No duplicate titles.</div>
        )}
      </div>
    </div>
  );
}

function ComponentsTab({ index }) {
  // Group by size for compact display.
  const bySize = index.components.reduce((acc, size) => {
    acc[size] = (acc[size] || 0) + 1;
    return acc;
  }, {});
  const rows = Object.entries(bySize)
    .map(([size, count]) => ({ size: Number(size), count }))
    .sort((a, b) => b.size - a.size);
  return (
    <div className="vault-list-panel">
      <div className="vault-list">
        {rows.map(({ size, count }) => (
          <div key={size} className="vault-list-row">
            <span className="vault-list-title">
              {count} component{count === 1 ? "" : "s"} of size {size}
              {size === 1 && " (isolated notes)"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
