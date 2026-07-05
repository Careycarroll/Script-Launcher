import { useState, useEffect, useRef, useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";
import TerminalPanel from "../Terminal";
const {
  VaultStart,
  VaultQuery,
  VaultStop,
  PickFolder,
  GetGroups,
  RunScript,
  PtyCreate,
  PtyKill,
  SaveFile,
  OpenExternal,
} = window.electronAPI;

const STORAGE_KEY = "vault-workbench-path";
const VAULT_NAME_KEY = "vault-workbench-name";
const DEFAULT_VAULT_PATH =
  "/Users/careycarroll/Library/Mobile Documents/iCloud~md~obsidian/Documents/CAWC Vaulting";

let reqCounter = 0;
const nextId = () => `r${++reqCounter}`;

const TABS = [
  "Overview",
  "Graph",
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
  const [vaultName, setVaultName] = useState(
    () => localStorage.getItem(VAULT_NAME_KEY) || "CAWC Vaulting",
  );
  const [status, setStatus] = useState("stopped");
  const [error, setError] = useState("");
  const [index, setIndex] = useState(null);
  const [busy, setBusy] = useState(false);
  const [alsoInDomain, setAlsoInDomain] = useState([]);
  const [activeTab, setActiveTab] = useState("Overview");
  const [headerCollapsed, setHeaderCollapsed] = useState(false);
  const [footerCollapsed, setFooterCollapsed] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalReady, setTerminalReady] = useState(false);
  const [terminalTitle, setTerminalTitle] = useState("");
  const [pendingTerminalLaunch, setPendingTerminalLaunch] = useState(null);

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
  useEffect(() => {
    localStorage.setItem(VAULT_NAME_KEY, vaultName);
  }, [vaultName]);
  useEffect(
    () => () => {
      VaultStop();
    },
    [],
  );

  useEffect(() => {
    if (!terminalReady || !pendingTerminalLaunch) return;

    const launch = async () => {
      await PtyCreate(pendingTerminalLaunch.path, pendingTerminalLaunch.args);
      setPendingTerminalLaunch(null);
    };

    launch();
  }, [terminalReady, pendingTerminalLaunch]);

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
    } catch {}
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

  async function closeTerminal() {
    await PtyKill();
    setTerminalOpen(false);
    setTerminalReady(false);
    setPendingTerminalLaunch(null);
  }

  async function runAlsoInDomain(entry) {
    if (entry.interactive) {
      setTerminalTitle(entry.name);
      setTerminalOpen(true);
      setTerminalReady(false);
      setPendingTerminalLaunch({
        path: entry.path,
        args: [],
      });
    } else {
      const result = await RunScript(entry.groupIdx, entry.scriptIdx, []);
      alert(result.output || result.error || "(no output)");
    }
  }

  async function exportJSON() {
    if (!index) return;
    await SaveFile({
      defaultName: "vault-index.json",
      content: JSON.stringify(index, null, 2),
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
  }

  async function exportGraphML() {
    if (!index) return;
    const escape = (s) =>
      String(s).replace(
        /[<>&"]/g,
        (c) =>
          ({
            "<": "&lt;",
            ">": "&gt;",
            "&": "&amp;",
            '"': "&quot;",
          })[c],
      );
    const inDegree = new Map();
    index.edges.forEach((e) =>
      inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1),
    );

    const lines = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
      '  <key id="title" for="node" attr.name="title" attr.type="string"/>',
      '  <key id="tags" for="node" attr.name="tags" attr.type="string"/>',
      '  <key id="in_degree" for="node" attr.name="in_degree" attr.type="int"/>',
      '  <key id="type" for="edge" attr.name="type" attr.type="string"/>',
      '  <graph id="vault" edgedefault="directed">',
    ];
    index.notes.forEach((n) => {
      lines.push(`    <node id="${escape(n.title)}">`);
      lines.push(`      <data key="title">${escape(n.title)}</data>`);
      lines.push(
        `      <data key="tags">${escape((n.tags || []).join(","))}</data>`,
      );
      lines.push(
        `      <data key="in_degree">${inDegree.get(n.title) || 0}</data>`,
      );
      lines.push(`    </node>`);
    });
    index.edges.forEach((e, i) => {
      lines.push(
        `    <edge id="e${i}" source="${escape(e.source)}" target="${escape(e.target)}">`,
      );
      lines.push(`      <data key="type">${escape(e.type)}</data>`);
      lines.push(`    </edge>`);
    });
    lines.push("  </graph>");
    lines.push("</graphml>");

    await SaveFile({
      defaultName: "vault-graph.graphml",
      content: lines.join("\n"),
      filters: [{ name: "GraphML", extensions: ["graphml"] }],
    });
  }

  async function exportMermaid() {
    if (!index) return;
    const inDegree = new Map();
    index.edges.forEach((e) =>
      inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1),
    );
    const topEdges = [...index.edges]
      .sort(
        (a, b) => (inDegree.get(b.target) || 0) - (inDegree.get(a.target) || 0),
      )
      .slice(0, 500);
    const sanitize = (s) =>
      String(s)
        .replace(/[^a-zA-Z0-9]/g, "_")
        .slice(0, 40);
    const seen = new Set();
    const lines = ["graph LR"];
    topEdges.forEach((e) => {
      const s = sanitize(e.source);
      const t = sanitize(e.target);
      if (!seen.has(s)) {
        lines.push(`  ${s}["${e.source.replace(/"/g, "'")}"]`);
        seen.add(s);
      }
      if (!seen.has(t)) {
        lines.push(`  ${t}["${e.target.replace(/"/g, "'")}"]`);
        seen.add(t);
      }
      lines.push(`  ${s} --> ${t}`);
    });
    await SaveFile({
      defaultName: "vault-graph.mmd",
      content: lines.join("\n"),
      filters: [{ name: "Mermaid", extensions: ["mmd", "md"] }],
    });
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
      <div className={`vault-header ${headerCollapsed ? "collapsed" : ""}`}>
        <button
          className="vault-collapse-toggle"
          onClick={() => setHeaderCollapsed((c) => !c)}
          title={headerCollapsed ? "Expand header" : "Collapse header"}
        >
          {headerCollapsed ? "▾" : "▴"}
        </button>
        {!headerCollapsed && (
          <>
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
                  <button
                    className="btn-secondary"
                    onClick={stop}
                    disabled={busy}
                  >
                    Stop
                  </button>
                </>
              )}
            </div>
            {error && <div className="vault-error">{error}</div>}
            {index && (
              <div className="vault-export-row">
                <span className="vault-export-label">Export:</span>
                <button className="btn-secondary" onClick={exportJSON}>
                  JSON
                </button>
                <button className="btn-secondary" onClick={exportGraphML}>
                  GraphML
                </button>
                <button className="btn-secondary" onClick={exportMermaid}>
                  Mermaid
                </button>
                <span className="vault-name-label">Obsidian vault name:</span>
                <input
                  className="vault-name-input"
                  value={vaultName}
                  onChange={(e) => setVaultName(e.target.value)}
                  disabled={status !== "stopped"}
                />
              </div>
            )}
          </>
        )}
        {headerCollapsed && (
          <span
            className="vault-collapse-summary"
            style={{ color: statusColor }}
          >
            {statusDot} {status} · {vaultPath.split("/").pop()}
          </span>
        )}
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
            {activeTab === "Graph" && (
              <GraphTab index={index} vaultName={vaultName} />
            )}
            {activeTab === "Orphans" && <OrphansTab index={index} />}
            {activeTab === "Broken Links" && <BrokenLinksTab index={index} />}
            {activeTab === "Tags" && <TagsTab index={index} />}
            {activeTab === "Duplicates" && <DuplicatesTab index={index} />}
            {activeTab === "Components" && <ComponentsTab index={index} />}
          </div>
        </>
      )}

      {terminalOpen && (
        <div className="embedded-terminal-panel">
          <div className="embedded-terminal-header">
            <span>Terminal — {terminalTitle}</span>
            <button className="btn-secondary" onClick={closeTerminal}>
              Close Terminal
            </button>
          </div>
          <div className="embedded-terminal-body">
            <TerminalPanel
              autoStartShell={false}
              onReady={() => setTerminalReady(true)}
            />
          </div>
        </div>
      )}

      {alsoInDomain.length > 0 && (
        <div className={`vault-also ${footerCollapsed ? "collapsed" : ""}`}>
          <button
            className="vault-collapse-toggle"
            onClick={() => setFooterCollapsed((c) => !c)}
            title={footerCollapsed ? "Expand footer" : "Collapse footer"}
          >
            {footerCollapsed ? "▴" : "▾"}
          </button>
          {!footerCollapsed && (
            <>
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
            </>
          )}
          {footerCollapsed && (
            <span className="vault-collapse-summary">
              Also in Vault ({alsoInDomain.length})
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function tabCount(tab, idx) {
  switch (tab) {
    case "Overview":
      return idx.note_count;
    case "Graph":
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

// ── Overview ──
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

// ── Graph ──
function GraphTab({ index, vaultName }) {
  const containerRef = useRef(null);
  const graphRef = useRef(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [selectedTitle, setSelectedTitle] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterPreset, setFilterPreset] = useState("all");

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setSize({ width: Math.max(200, width), height: Math.max(300, height) });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const graphData = useMemo(() => {
    const inDegree = new Map();
    index.edges.forEach((e) => {
      inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
    });
    const nodes = index.notes.map((n) => ({
      id: n.title,
      title: n.title,
      tags: n.tags,
      rel_path: n.rel_path,
      in_degree: inDegree.get(n.title) || 0,
    }));
    const links = index.edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }));
    return { nodes, links };
  }, [index]);

  const nodeById = useMemo(() => {
    const m = new Map();
    graphData.nodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [graphData]);

  const brokenLinkSources = useMemo(() => {
    const s = new Set();
    index.broken_links.forEach((l) => s.add(l.source));
    return s;
  }, [index]);

  function matchesFilter(node) {
    if (filterPreset === "hubs" && node.in_degree < 5) return false;
    if (filterPreset === "orphans" && node.in_degree > 0) return false;
    if (filterPreset === "broken-source" && !brokenLinkSources.has(node.title))
      return false;
    if (filterPreset === "has-tags" && (!node.tags || node.tags.length === 0))
      return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const inTitle = node.title.toLowerCase().includes(q);
      const inTags = (node.tags || []).some((t) => t.toLowerCase().includes(q));
      if (!inTitle && !inTags) return false;
    }
    return true;
  }

  const selectedNode = selectedTitle ? nodeById.get(selectedTitle) : null;

  const nodeColor = (n) => {
    const matches = matchesFilter(n);
    if (selectedTitle && n.id === selectedTitle)
      return matches ? "#ff9e64" : "rgba(255, 158, 100, 0.3)";
    if (!matches) return "rgba(75, 156, 211, 0.15)";
    if (n.in_degree === 0) return "#8899b4";
    return "#4B9CD3";
  };

  function focusNode(title) {
    setSelectedTitle(title);
    const node = nodeById.get(title);
    if (node && graphRef.current && node.x != null && node.y != null) {
      graphRef.current.centerAt(node.x, node.y, 500);
      graphRef.current.zoom(3, 500);
    }
  }

  return (
    <div ref={containerRef} className="vault-graph-container">
      <div className="vault-graph-controls">
        <input
          className="vault-graph-search"
          placeholder="Search title or tag…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <div className="vault-graph-presets">
          {[
            ["all", "All"],
            ["hubs", "Hubs (5+)"],
            ["orphans", "Orphans"],
            ["broken-source", "Has broken"],
            ["has-tags", "Has tags"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={`vault-preset ${filterPreset === key ? "active" : ""}`}
              onClick={() => setFilterPreset(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        width={size.width}
        height={size.height}
        backgroundColor="#0d1117"
        nodeLabel={(n) => `${n.title} (${n.in_degree} in)`}
        nodeVal={(n) => Math.max(0.5, Math.sqrt(n.in_degree + 1))}
        nodeColor={nodeColor}
        nodeRelSize={4}
        linkColor={() => "rgba(122, 162, 247, 0.25)"}
        linkWidth={0.5}
        onNodeClick={(n) => setSelectedTitle(n.id)}
        onBackgroundClick={() => setSelectedTitle(null)}
        cooldownTicks={200}
        warmupTicks={100}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.4}
      />
      <div className="vault-graph-legend">
        <div>
          <span
            className="vault-graph-swatch"
            style={{ background: "#4B9CD3" }}
          />{" "}
          connected
        </div>
        <div>
          <span
            className="vault-graph-swatch"
            style={{ background: "#8899b4" }}
          />{" "}
          orphan / no incoming
        </div>
        <div>
          <span
            className="vault-graph-swatch"
            style={{ background: "#ff9e64" }}
          />{" "}
          selected
        </div>
      </div>
      {selectedNode && (
        <NoteSidePanel
          index={index}
          selectedNode={selectedNode}
          onClose={() => setSelectedTitle(null)}
          onNavigate={focusNode}
          vaultName={vaultName}
        />
      )}
    </div>
  );
}

// ── Side panel ──
function NoteSidePanel({
  index,
  selectedNode,
  onClose,
  onNavigate,
  vaultName,
}) {
  const [noteData, setNoteData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [noteError, setNoteError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNoteError("");
    setNoteData(null);
    VaultQuery({
      id: nextId(),
      method: "get_note",
      params: { title: selectedNode.title },
    })
      .then((res) => {
        if (!cancelled) setNoteData(res);
      })
      .catch((err) => {
        if (!cancelled) setNoteError(String(err?.message || err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNode.title]);

  const backlinks = useMemo(() => {
    const set = new Set();
    index.edges.forEach((e) => {
      if (e.target === selectedNode.title) set.add(e.source);
    });
    return Array.from(set).sort();
  }, [index, selectedNode.title]);

  const forwardLinks = useMemo(() => {
    const set = new Set();
    index.edges.forEach((e) => {
      if (e.source === selectedNode.title) set.add(e.target);
    });
    return Array.from(set).sort();
  }, [index, selectedNode.title]);

  const similarByTags = useMemo(() => {
    if (!selectedNode.tags || selectedNode.tags.length === 0) return [];
    const selectedTags = new Set(selectedNode.tags);
    const overlaps = index.notes
      .filter((n) => n.title !== selectedNode.title && n.tags?.length > 0)
      .map((n) => {
        const shared = n.tags.filter((t) => selectedTags.has(t));
        return { title: n.title, shared_count: shared.length, shared };
      })
      .filter((x) => x.shared_count > 0)
      .sort((a, b) => b.shared_count - a.shared_count)
      .slice(0, 20);
    return overlaps;
  }, [index, selectedNode.title, selectedNode.tags]);

  async function openInObsidian() {
    const uri = `obsidian://open?vault=${encodeURIComponent(vaultName)}&file=${encodeURIComponent(selectedNode.title)}`;
    await OpenExternal(uri);
  }

  return (
    <aside className="vault-side-panel">
      <div className="vault-side-header">
        <div className="vault-side-title">{selectedNode.title}</div>
        <button className="vault-side-close" onClick={onClose}>
          ✕
        </button>
      </div>
      <button className="vault-side-obsidian" onClick={openInObsidian}>
        Open in Obsidian ↗
      </button>
      <div className="vault-side-meta">
        <span>
          {backlinks.length} backlink{backlinks.length === 1 ? "" : "s"}
        </span>
        <span>·</span>
        <span>{forwardLinks.length} forward</span>
        <span>·</span>
        <span>
          {selectedNode.tags?.length || 0} tag
          {selectedNode.tags?.length === 1 ? "" : "s"}
        </span>
      </div>
      {selectedNode.tags?.length > 0 && (
        <div className="vault-side-tags">
          {selectedNode.tags.map((t) => (
            <span key={t} className="vault-side-tag">
              {t}
            </span>
          ))}
        </div>
      )}
      <div className="vault-side-path">{selectedNode.rel_path}</div>

      <div className="vault-side-section">
        <div className="vault-side-section-heading">Content</div>
        <div className="vault-side-content">
          {loading && <div className="vault-side-loading">Loading…</div>}
          {noteError && (
            <div className="vault-side-error">Failed to load: {noteError}</div>
          )}
          {noteData && <pre className="vault-side-body">{noteData.body}</pre>}
        </div>
      </div>

      <div className="vault-side-section">
        <div className="vault-side-section-heading">
          Backlinks <span className="vault-side-count">{backlinks.length}</span>
        </div>
        <div className="vault-side-list">
          {backlinks.map((t) => (
            <button
              key={t}
              className="vault-side-link"
              onClick={() => onNavigate(t)}
            >
              {t}
            </button>
          ))}
          {backlinks.length === 0 && (
            <div className="vault-side-empty">No backlinks.</div>
          )}
        </div>
      </div>

      <div className="vault-side-section">
        <div className="vault-side-section-heading">
          Forward links{" "}
          <span className="vault-side-count">{forwardLinks.length}</span>
        </div>
        <div className="vault-side-list">
          {forwardLinks.map((t) => (
            <button
              key={t}
              className="vault-side-link"
              onClick={() => onNavigate(t)}
            >
              {t}
            </button>
          ))}
          {forwardLinks.length === 0 && (
            <div className="vault-side-empty">No forward links.</div>
          )}
        </div>
      </div>

      <div className="vault-side-section">
        <div className="vault-side-section-heading">
          Similar by tags{" "}
          <span className="vault-side-count">{similarByTags.length}</span>
        </div>
        <div className="vault-side-list">
          {similarByTags.map((s) => (
            <button
              key={s.title}
              className="vault-side-link"
              onClick={() => onNavigate(s.title)}
            >
              <span className="vault-side-link-title">{s.title}</span>
              <span className="vault-side-link-badge">{s.shared_count}</span>
            </button>
          ))}
          {similarByTags.length === 0 && (
            <div className="vault-side-empty">
              {selectedNode.tags?.length
                ? "No notes share any tags."
                : "No tags on this note."}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

// ── Orphans ──
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

// ── Broken Links ──
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

// ── Tags ──
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

// ── Duplicates ──
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

// ── Components ──
function ComponentsTab({ index }) {
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
