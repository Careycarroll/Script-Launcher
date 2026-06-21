import { useState, useEffect } from 'react';
import { GetGroups, RunScript, PickFile, PickFolder } from '../wailsjs/go/main/App';
import './App.css';

function App() {
  const [groups, setGroups]       = useState([]);
  const [selected, setSelected]   = useState(null); // { groupIdx, scriptIdx }
  const [args, setArgs]           = useState([]);
  const [fileQueue, setFileQueue] = useState([]); // for multiFile args
  const [queueMode, setQueueMode] = useState(null); // null | 'file' | 'folder'
  const [output, setOutput]       = useState('');
  const [status, setStatus]       = useState('idle'); // idle | running | success | error

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
    setArgs(s.argDefs ? s.argDefs.map(d => d.default || '') : []);
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
    const path = await PickFile();
    if (path) setArg(argIdx, path);
  }

  async function pickFolder(argIdx) {
    const path = await PickFolder();
    if (path) setArg(argIdx, path);
  }

  async function addToQueue(dirMode) {
    const path = dirMode ? await PickFolder() : await PickFile();
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

    // Collect non-multiFile args using original indices
    const nonMultiArgs = (script.argDefs || [])
      .map((def, i) => (!def.multiFile && args[i] !== '' ? args[i] : null))
      .filter(a => a !== null);

    const finalArgs = isMultiFile
      ? [...fileQueue, ...nonMultiArgs]
      : args.filter(a => a !== '');

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
    <div className="app">

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <nav className="sidebar">
        <div className="sidebar-title">⚡ Script Launcher</div>
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

              {/* Standard args — rendered using original index to keep args[] aligned */}
              {script.argDefs?.map((def, i) => {
                if (def.multiFile) return null;
                return (
                  <div key={i} className="arg-group">
                    <div className="arg-label">{def.label}</div>
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
  );
}

export default App;
