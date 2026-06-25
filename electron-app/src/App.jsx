import { useState, useEffect } from 'react';
const { GetGroups, RunScript, PickFile, PickFolder, PtyCreate } = window.electronAPI;
import TerminalPanel from './Terminal';
import './App.css';

function App() {
  const [groups, setGroups]       = useState([]);
  const [selected, setSelected]   = useState(null); // { groupIdx, scriptIdx }
  const [args, setArgs]           = useState([]);
  const [fileQueue, setFileQueue] = useState([]); // for multiFile args
  const [queueMode, setQueueMode] = useState(null); // null | 'file' | 'folder'
  const [output, setOutput]       = useState('');
  const [status, setStatus]       = useState('idle'); // idle | running | success | error
  const [activeTab, setActiveTab]   = useState('scripts'); // scripts | terminal

  useEffect(() => {
    GetGroups().then(setGroups);
  }, []);

  // ── Derived state ───────────────────────────────────────────────────────────
  const script = selected
    ? groups[selected.groupIdx]?.scripts[selected.scriptIdx]
    : null;

  const isMultiFile = script?.argDefs?.some(d => d.multiFile) ?? false;
  const queueHasFiles = queueMode === 'file';
  const queueHasFolder = queueMode === 'folder';

  // ── Script selection ────────────────────────────────────────────────────────
  function selectScript(groupIdx, scriptIdx) {
    const s = groups[groupIdx].scripts[scriptIdx];
    setSelected({ groupIdx, scriptIdx });
    // Default-initialize args. Checkboxes (booleans) need explicit string
    // representation so the existing string[] state works unchanged.
    setArgs(s.argDefs ? s.argDefs.map(d => {
      if (d.type === 'checkbox') return d.default ? 'true' : 'false';
      if (d.default == null) return '';
      return String(d.default);
    }) : []);
    setFileQueue([]);
    setQueueMode(null);
    setOutput('');
    setStatus('idle');
  }

  // ── Arg input ───────────────────────────────────────────────────────────────
  function setArg(i, value) {
    const next = [...args];
    next[i] = value;
    setArgs(next);
  }

  // ── File / folder pickers ───────────────────────────────────────────────────
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
    const multiDef = script.argDefs?.find(d => d.multiFile);
    const path = dirMode ? await PickFolder() : await PickFile(multiDef?.extensions);
    if (path) {
      setFileQueue(q => [...q, path]);
      setQueueMode(dirMode ? 'folder' : 'file');
    }
  }

  function removeFromQueue(idx) {
    setFileQueue(q => {
      const next = q.filter((_, i) => i !== idx);
      if (next.length === 0) setQueueMode(null);
      return next;
    });
  }

  // ── Run ─────────────────────────────────────────────────────────────────────
  async function runScript() {
    if (!selected) return;
    setStatus('running');
    setOutput('');

    // Build argv client-side: walk argDefs, attach flags to values, collect
    // positionals in order. Pass verbatim to main.ts — no index-based
    // reconstruction in main, which breaks when multiFile expands the array.
    //
    // Per-widget rules:
    //   checkbox + invertFlag: pass --flag only when UNchecked
    //   checkbox (no invert):  pass --flag only when checked (no value)
    //   number:                skip empty; otherwise pass --flag <value>
    //   anything else:         skip empty; pass --flag <value> or positional
    const flags = [];
    const positional = [];
    (script.argDefs || []).forEach((def, i) => {
      if (def.multiFile) return;
      const v = args[i];

      // Hidden boolean flags (store_true style): emit flag alone, no value.
      if (def.hidden && def.flag && def.default === true) {
        flags.push(def.flag);
        return;
      }

      if (def.type === 'checkbox') {
        const checked = v === 'true' || v === true;
        if (def.invertFlag) {
          if (!checked && def.flag) flags.push(def.flag);
        } else {
          if (checked && def.flag) flags.push(def.flag);
        }
        return;
      }

      if (v === '' || v == null) return;
      if (def.flag) { flags.push(def.flag, String(v)); return; }
      positional.push(String(v));
    });

    const finalArgs = isMultiFile
      ? [...flags, ...fileQueue, ...positional]
      : [...flags, ...positional];

    if (script.interactive) {
      setActiveTab('terminal');
      await PtyCreate(script.path, finalArgs);
      setStatus('idle');
      return;
    }
    const result = await RunScript(selected.groupIdx, selected.scriptIdx, finalArgs);

    setOutput(result.output || result.error || '(no output)');
    setStatus(result.error ? 'error' : 'success');
  }

  function clear() {
    setOutput('');
    setStatus('idle');
    setFileQueue([]);
    setQueueMode(null);
  }

  // ── Status label ────────────────────────────────────────────────────────────
  const statusLabel = {
    idle:    '',
    running: '⟳ Running',
    success: '✓ Success',
    error:   '✗ Error',
  }[status];

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="app-wrapper">
      <header className="tab-bar">
        <span className="tab-bar-title">⚡ Script Launcher</span>
        <div className="tabs">
          <button className={`tab ${activeTab === 'scripts' ? 'active' : ''}`} onClick={() => setActiveTab('scripts')}>Scripts</button>
          <button className={`tab ${activeTab === 'terminal' ? 'active' : ''}`} onClick={() => setActiveTab('terminal')}>Terminal</button>
        </div>
      </header>
      <div className="app" style={{ display: activeTab === 'scripts' ? 'flex' : 'none' }}>

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <nav className="sidebar">
        {groups.map((group, gi) => (
          <div key={gi}>
            <div className="group-label">{group.name}</div>
            {group.scripts.map((s, si) => (
              <div
                key={si}
                className={`nav-item ${
                  selected?.groupIdx === gi && selected?.scriptIdx === si ? 'active' : ''
                }`}
                onClick={() => selectScript(gi, si)}
              >
                <span className="nav-dot" />
                {s.name}
              </div>
            ))}
          </div>
        ))}
      </nav>

      {/* ── Detail Panel ─────────────────────────────────────────────────── */}
      <main className="detail">
        {!script ? (
          <div className="empty-state">Select a script to get started</div>
        ) : (
          <>
            {/* Header */}
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

            {/* Args */}
            <div className="args-section">

              {/* Multi-file queue */}
              {isMultiFile && (
                <>
                  <div className="arg-label">Files / Folders</div>
                  <div className="file-queue">
                    {fileQueue.length === 0 && (
                      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 8 }}>
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
                    <button className="btn-pick" onClick={() => addToQueue(false)} disabled={queueHasFolder}>
                      + Add File
                    </button>
                    {script.argDefs?.some(d => d.dirPicker) && (
                      <button className="btn-pick" onClick={() => addToQueue(true)} disabled={queueHasFiles}>
                        + Add Folder
                      </button>
                    )}
                  </div>
                </>
              )}

              {/* Standard args — rendered using original index to keep args[] aligned.
                  Widget chosen by def.type, falling back to options/text. */}
              {script.argDefs?.map((def, i) => {
                if (def.multiFile) return null;
                if (def.hidden) return null;

                const label = (
                  <div className="arg-label">
                    {def.label}
                    {def.tooltip && (
                      <span className="arg-tooltip" title={def.tooltip}>?</span>
                    )}
                  </div>
                );

                // Checkbox
                if (def.type === 'checkbox') {
                  const checked = args[i] === 'true' || args[i] === true;
                  return (
                    <div key={i} className="arg-group">
                      {label}
                      <div className="arg-row">
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={e => setArg(i, e.target.checked ? 'true' : 'false')}
                          />
                          <span>{def.checkboxLabel || 'Enabled'}</span>
                        </label>
                      </div>
                    </div>
                  );
                }

                // Number
                if (def.type === 'number') {
                  return (
                    <div key={i} className="arg-group">
                      {label}
                      <div className="arg-row">
                        <input
                          type="number"
                          className="arg-input"
                          value={args[i] ?? ''}
                          placeholder={def.default != null ? String(def.default) : ''}
                          min={def.min}
                          max={def.max}
                          step={def.step || 1}
                          onChange={e => setArg(i, e.target.value)}
                        />
                      </div>
                    </div>
                  );
                }

                // Output directory picker — text + Pick Folder, labeled for output
                if (def.type === 'outputDir') {
                  return (
                    <div key={i} className="arg-group">
                      {label}
                      <div className="arg-row">
                        <input
                          className="arg-input"
                          value={args[i] || ''}
                          placeholder={def.placeholder || 'Same as input folder'}
                          onChange={e => setArg(i, e.target.value)}
                        />
                        <button className="btn-pick" onClick={() => pickFolder(i)}>
                          Pick Folder
                        </button>
                      </div>
                    </div>
                  );
                }

                // Default: dropdown if options, else text input (existing behavior).
                return (
                  <div key={i} className="arg-group">
                    {label}
                    <div className="arg-row">
                      {def.options && def.options.length > 0 ? (
                        <select
                          className="arg-input"
                          value={args[i] || def.default || ''}
                          onChange={e => setArg(i, e.target.value)}
                        >
                          {def.options.map(opt => (
                            <option key={opt} value={opt}>{opt}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          className="arg-input"
                          value={args[i] || ''}
                          placeholder={def.default || ''}
                          onChange={e => setArg(i, e.target.value)}
                        />
                      )}
                      {def.filePicker && (
                        <button className="btn-pick" onClick={() => pickFile(i)}>
                          Pick File
                        </button>
                      )}
                      {def.dirPicker && !def.multiFile && (
                        <button className="btn-pick" onClick={() => pickFolder(i)}>
                          Pick Folder
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Output */}
            {output && (
              <div className={`output-panel ${status === 'error' ? 'error' : ''}`}>
                {output}
              </div>
            )}

            {/* Footer */}
            <div className="detail-footer">
              <button
                className="btn-run"
                onClick={runScript}
                disabled={status === 'running'}
              >
                {status === 'running' ? 'Running…' : 'Run Script'}
              </button>
              <button className="btn-secondary" onClick={clear}>
                Clear
              </button>
              <div className={`status-badge ${status}`}>
                {statusLabel}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
    <div className="terminal-tab" style={{ display: activeTab === 'terminal' ? 'flex' : 'none' }}>
        <TerminalPanel />
      </div>
    </div>
  );
}

export default App;
