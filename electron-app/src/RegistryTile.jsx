import { useState, useEffect, useRef } from "react";
const { GetGroups, RunScript, PickFile, PickFolder, PtyCreate, PtyKill } =
  window.electronAPI;
import WidgetRenderer from "./WidgetRenderer";
import BookmarkEditor from "./features/BookmarkEditor";
import TerminalPanel from "./Terminal";

// Shared tile body for registry-driven domains (Documents, Vault, Media,
// Developer). Filters the flat registry by `domain`, renders a sidebar of
// matching entries, and hosts the detail panel using the existing widget
// renderer + bookmark editor.
//
// Bespoke component registry. Keyed by the `component` field on a
// registry entry. Missing key = fall back to WidgetRenderer.
const COMPONENTS = {
  BookmarkEditor,
};
// Bespoke tiles (future Vault Workbench, Video Silence Trim previews) will
// be their own components — they don't use RegistryTile.
export default function RegistryTile({ domain, title }) {
  const [entries, setEntries] = useState([]); // flat list, already filtered
  const [selected, setSelected] = useState(null); // index into entries
  const [rawGroups, setRawGroups] = useState([]); // needed for RunScript indices
  const [args, setArgs] = useState([]);
  const [fileQueue, setFileQueue] = useState([]);
  const [queueMode, setQueueMode] = useState(null);
  const [output, setOutput] = useState("");
  const [status, setStatus] = useState("idle");
  const [bookmarkCanApply, setBookmarkCanApply] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalReady, setTerminalReady] = useState(false);
  const [terminalTitle, setTerminalTitle] = useState("");
  const [pendingTerminalLaunch, setPendingTerminalLaunch] = useState(null);
  const bookmarkRef = useRef(null);

  useEffect(() => {
    GetGroups().then((groups) => {
      setRawGroups(groups);
      // Flatten and filter, but remember original (groupIdx, scriptIdx) so
      // RunScript can still address by registry position.
      const flat = [];
      groups.forEach((group, gi) => {
        (group.scripts || []).forEach((s, si) => {
          const d = s.domain || "documents";
          if (d === domain) flat.push({ ...s, groupIdx: gi, scriptIdx: si });
        });
      });
      setEntries(flat);
    });
  }, [domain]);

  useEffect(() => {
    if (!terminalReady || !pendingTerminalLaunch) return;

    const launch = async () => {
      await PtyCreate(pendingTerminalLaunch.path, pendingTerminalLaunch.args);
      setPendingTerminalLaunch(null);
      setStatus("idle");
    };

    launch();
  }, [terminalReady, pendingTerminalLaunch]);

  const script = selected != null ? entries[selected] : null;
  const isMultiFile = script?.argDefs?.some((d) => d.multiFile) ?? false;
  const BespokeComponent = script?.component
    ? COMPONENTS[script.component]
    : null;
  const usesBespoke = BespokeComponent != null;
  const queueHasFiles = queueMode === "file";
  const queueHasFolder = queueMode === "folder";

  function selectScript(idx) {
    const s = entries[idx];
    setSelected(idx);
    setArgs(
      s.argDefs
        ? s.argDefs.map((d) => {
            if (d.type === "checkbox") return d.default ? "true" : "false";
            if (d.default == null) return "";
            return String(d.default);
          })
        : [],
    );
    setFileQueue([]);
    setQueueMode(null);
    setOutput("");
    setStatus("idle");
    setBookmarkCanApply(false);
    setTerminalOpen(false);
    setTerminalReady(false);
    setPendingTerminalLaunch(null);
    bookmarkRef.current?.reset();
  }

  function setArg(i, value) {
    const next = [...args];
    next[i] = value;
    setArgs(next);
  }

  async function pickFile(argIdx) {
    const def = script.argDefs?.[argIdx];
    const path = await PickFile(def?.extensions);
    if (path) setArg(argIdx, path);
  }
  async function pickFolder(argIdx) {
    const path = await PickFolder();
    if (path) setArg(argIdx, path);
  }
  async function addToQueue(dirMode) {
    const multiDef = script.argDefs?.find((d) => d.multiFile);
    const path = dirMode
      ? await PickFolder()
      : await PickFile(multiDef?.extensions);
    if (path) {
      setFileQueue((q) => [...q, path]);
      setQueueMode(dirMode ? "folder" : "file");
    }
  }
  function removeFromQueue(idx) {
    setFileQueue((q) => {
      const next = q.filter((_, i) => i !== idx);
      if (next.length === 0) setQueueMode(null);
      return next;
    });
  }

  async function runScript() {
    if (!script) return;
    setStatus("running");
    setOutput("");

    const flags = [];
    const positional = [];
    (script.argDefs || []).forEach((def, i) => {
      if (def.multiFile) return;
      if (def.showWhen) {
        const sw = def.showWhen;
        const targetIdx = (script.argDefs || []).findIndex(d => d.label === sw.field);
        if (targetIdx >= 0) {
          const targetVal = args[targetIdx] ?? script.argDefs[targetIdx].default;
          const hidden = sw.in ? !sw.in.includes(targetVal) : targetVal !== sw.value;
          if (hidden) return;
        }
      }
      const v = args[i];
      if (def.hidden && def.flag && def.default === true) {
        flags.push(def.flag);
        return;
      }
      if (def.type === "checkbox") {
        const checked = v === "true" || v === true;
        if (def.invertFlag) {
          if (!checked && def.flag) flags.push(def.flag);
        } else {
          if (checked && def.flag) flags.push(def.flag);
        }
        return;
      }
      if (v === "" || v == null) return;
      if (def.flag) {
        flags.push(def.flag, String(v));
        return;
      }
      positional.push(String(v));
    });

    const finalArgs = isMultiFile
      ? [...flags, ...fileQueue, ...positional]
      : [...flags, ...positional];

    if (script.interactive) {
      setTerminalTitle(script.name);
      setTerminalOpen(true);
      setPendingTerminalLaunch({
        path: script.path,
        args: finalArgs,
        nonce: Date.now(),
      });
      return;
    }
    const result = await RunScript(
      script.groupIdx,
      script.scriptIdx,
      finalArgs,
    );
    setOutput(result.output || result.error || "(no output)");
    setStatus(result.error ? "error" : "success");
  }

  function clear() {
    setOutput("");
    setStatus("idle");
    setFileQueue([]);
    setQueueMode(null);
    setBookmarkCanApply(false);
    bookmarkRef.current?.reset();
  }

  async function closeTerminal() {
    await PtyKill();
    setTerminalOpen(false);
    setTerminalReady(false);
    setPendingTerminalLaunch(null);
    setStatus("idle");
  }

  const statusLabel = {
    idle: "",
    running: "⟳ Running",
    success: "✓ Success",
    error: "✗ Error",
  }[status];

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="sidebar-title">{title}</div>
        {entries.length === 0 && (
          <div className="empty-state" style={{ padding: 16, fontSize: 13 }}>
            No entries in this domain yet.
          </div>
        )}
        {entries.map((s, i) => (
          <div
            key={i}
            className={`nav-item ${selected === i ? "active" : ""}`}
            onClick={() => selectScript(i)}
          >
            <span className="nav-dot" />
            {s.name}
          </div>
        ))}
      </nav>

      <main className="detail">
        {!script ? (
          <div className="empty-state">Select an entry to get started</div>
        ) : (
          <>
            <div className="detail-header">
              <div className="script-name">{script.name}</div>
              <div className="script-desc">{script.description}</div>
              {script.help && (
                <div className="help-box">
                  <strong>About</strong>
                  {script.help}
                </div>
              )}
            </div>

            <div className="args-section">
              {isMultiFile && (
                <>
                  <div className="arg-label">Files / Folders</div>
                  <div className="file-queue">
                    {fileQueue.length === 0 && (
                      <div
                        style={{
                          color: "var(--text-muted)",
                          fontSize: 12,
                          marginBottom: 8,
                        }}
                      >
                        No files queued yet
                      </div>
                    )}
                    {fileQueue.map((f, i) => (
                      <div key={i} className="file-queue-item">
                        <span>{f}</span>
                        <button onClick={() => removeFromQueue(i)}>✕</button>
                      </div>
                    ))}
                  </div>
                  <div className="queue-actions">
                    <button
                      className="btn-pick"
                      onClick={() => addToQueue(false)}
                      disabled={queueHasFolder}
                    >
                      + Add File
                    </button>
                    {script.argDefs?.some((d) => d.dirPicker) && (
                      <button
                        className="btn-pick"
                        onClick={() => addToQueue(true)}
                        disabled={queueHasFiles}
                      >
                        + Add Folder
                      </button>
                    )}
                  </div>
                </>
              )}

              {usesBespoke ? (
                <BespokeComponent
                  ref={bookmarkRef}
                  groups={rawGroups}
                  onStatusChange={setStatus}
                  onOutput={setOutput}
                  onCanApplyChange={setBookmarkCanApply}
                />
              ) : (
                <WidgetRenderer
                  argDefs={script.argDefs}
                  args={args}
                  setArg={setArg}
                  pickFile={pickFile}
                  pickFolder={pickFolder}
                />
              )}
            </div>

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

            {output && (
              <div
                className={`output-panel ${status === "error" ? "error" : ""}`}
              >
                {output}
              </div>
            )}

            <div className="detail-footer">
              {usesBespoke ? (
                <button
                  className="btn-run"
                  onClick={() => bookmarkRef.current?.apply()}
                  disabled={!bookmarkCanApply || status === "running"}
                >
                  Apply Bookmarks
                </button>
              ) : (
                <button
                  className="btn-run"
                  onClick={runScript}
                  disabled={status === "running"}
                >
                  {status === "running" ? "Running…" : "Run Script"}
                </button>
              )}
              <button className="btn-secondary" onClick={clear}>
                Clear
              </button>
              <div className={`status-badge ${status}`}>{statusLabel}</div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
