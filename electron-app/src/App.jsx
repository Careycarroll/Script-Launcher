import { useState, useEffect } from 'react';
const { GetGroups, RunScript, PickFile, PickFolder, PtyCreate, AnalyzeBookmarks } = window.electronAPI;
import TerminalPanel from './Terminal';
import './App.css';

// ── Theme variables (must match App.css :root) ─────────────────────────────
const THEME_VARS = {
  Backgrounds: [
    ['--bg-deep',      '#0d1117'],
    ['--bg-sidebar',   '#13294B'],
    ['--bg-surface',   '#1a2744'],
    ['--bg-card',      '#1f2f52'],
    ['--bg-input',     '#162238'],
  ],
  Accents: [
    ['--unc-blue',     '#4B9CD3'],
    ['--tokyo-blue',   '#7aa2f7'],
    ['--tokyo-cyan',   '#7dcfff'],
    ['--tokyo-purple', '#bb9af7'],
    ['--tokyo-green',  '#9ece6a'],
    ['--tokyo-red',    '#f7768e'],
    ['--tokyo-orange', '#ff9e64'],
  ],
  Text: [
    ['--text-primary', '#c0caf5'],
    ['--text-muted',   '#8899b4'],
    ['--text-heading', '#ffffff'],
  ],
};
const THEME_STORAGE_KEY = 'theme-overrides';

const THEME_PRESETS = {
  'UNC Night': {
    '--bg-deep': '#0d1117', '--bg-sidebar': '#13294B', '--bg-surface': '#1a2744',
    '--bg-card': '#1f2f52', '--bg-input': '#162238',
    '--unc-blue': '#4B9CD3', '--tokyo-blue': '#7aa2f7', '--tokyo-cyan': '#7dcfff',
    '--tokyo-purple': '#bb9af7', '--tokyo-green': '#9ece6a', '--tokyo-red': '#f7768e',
    '--tokyo-orange': '#ff9e64',
    '--text-primary': '#c0caf5', '--text-muted': '#8899b4', '--text-heading': '#ffffff',
  },
  'Dracula': {
    '--bg-deep': '#282a36', '--bg-sidebar': '#21222c', '--bg-surface': '#282a36',
    '--bg-card': '#343746', '--bg-input': '#21222c',
    '--unc-blue': '#bd93f9', '--tokyo-blue': '#6272a4', '--tokyo-cyan': '#8be9fd',
    '--tokyo-purple': '#ff79c6', '--tokyo-green': '#50fa7b', '--tokyo-red': '#ff5555',
    '--tokyo-orange': '#ffb86c',
    '--text-primary': '#f8f8f2', '--text-muted': '#6272a4', '--text-heading': '#ffffff',
  },
  'Nord': {
    '--bg-deep': '#2e3440', '--bg-sidebar': '#3b4252', '--bg-surface': '#3b4252',
    '--bg-card': '#434c5e', '--bg-input': '#3b4252',
    '--unc-blue': '#88c0d0', '--tokyo-blue': '#81a1c1', '--tokyo-cyan': '#8fbcbb',
    '--tokyo-purple': '#b48ead', '--tokyo-green': '#a3be8c', '--tokyo-red': '#bf616a',
    '--tokyo-orange': '#d08770',
    '--text-primary': '#e5e9f0', '--text-muted': '#7b8597', '--text-heading': '#eceff4',
  },
};

function loadThemeOverrides() {
  try { return JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) || '{}'); }
  catch { return {}; }
}
function applyOverride(name, value) {
  document.documentElement.style.setProperty(name, value);
}
function clearOverride(name) {
  document.documentElement.style.removeProperty(name);
}

function ThemePanel({ open, onClose }) {
  const [overrides, setOverrides] = useState(loadThemeOverrides);

  function setVar(name, value) {
    const next = { ...overrides, [name]: value };
    setOverrides(next);
    applyOverride(name, value);
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(next));
  }
  function resetVar(name) {
    const next = { ...overrides };
    delete next[name];
    setOverrides(next);
    clearOverride(name);
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(next));
  }
  function resetAll() {
    Object.keys(overrides).forEach(clearOverride);
    setOverrides({});
    localStorage.removeItem(THEME_STORAGE_KEY);
  }
  function applyPreset(name) {
    const preset = THEME_PRESETS[name];
    if (!preset) return;
    Object.entries(preset).forEach(([k, v]) => applyOverride(k, v));
    setOverrides(preset);
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(preset));
  }

  return (
    <>
      {open && <div className="theme-scrim" onClick={onClose} />}
      <aside className={`theme-drawer ${open ? 'open' : ''}`}>
        <div className="theme-drawer-header">
          <span>Theme</span>
          <button className="theme-close" onClick={onClose}>✕</button>
        </div>
        <div className="theme-drawer-body">
          <div className="theme-group">
            <div className="theme-group-label">Presets</div>
            <div className="theme-presets">
              {Object.keys(THEME_PRESETS).map(name => (
                <button key={name} className="theme-preset-btn" onClick={() => applyPreset(name)}>
                  {name}
                </button>
              ))}
            </div>
          </div>
          {Object.entries(THEME_VARS).map(([groupName, vars]) => (
            <div key={groupName} className="theme-group">
              <div className="theme-group-label">{groupName}</div>
              {vars.map(([name, defaultHex]) => {
                const current = overrides[name] || defaultHex;
                const isOverridden = name in overrides;
                return (
                  <div key={name} className="theme-row">
                    <label className="theme-var-name" title={name}>{name.replace('--','')}</label>
                    <input
                      type="color"
                      value={current}
                      onChange={e => setVar(name, e.target.value)}
                    />
                    <input
                      type="text"
                      className="theme-hex"
                      value={current}
                      onChange={e => {
                        const v = e.target.value;
                        if (/^#[0-9a-fA-F]{6}$/.test(v)) setVar(name, v);
                        else setOverrides({ ...overrides, [name]: v });
                      }}
                    />
                    <button
                      className="theme-reset"
                      onClick={() => resetVar(name)}
                      disabled={!isOverridden}
                      title="Reset to default"
                    >↺</button>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div className="theme-drawer-footer">
          <button className="btn-secondary" onClick={resetAll}>Reset all</button>
        </div>
      </aside>
    </>
  );
}

function App() {
  const [groups, setGroups]       = useState([]);
  const [selected, setSelected]   = useState(null); // { groupIdx, scriptIdx }
  const [args, setArgs]           = useState([]);
  const [fileQueue, setFileQueue] = useState([]); // for multiFile args
  const [queueMode, setQueueMode] = useState(null); // null | 'file' | 'folder'
  const [output, setOutput]       = useState('');
  const [status, setStatus]       = useState('idle'); // idle | running | success | error
  const [activeTab, setActiveTab]   = useState('scripts'); // scripts | terminal
  const [bookmarkPdfPath, setBookmarkPdfPath] = useState('');
  const [bookmarkText, setBookmarkText] = useState('');
  const [bookmarkInfo, setBookmarkInfo] = useState('');
  const [bookmarkAnalyzing, setBookmarkAnalyzing] = useState(false);
  const [bookmarkApplying, setBookmarkApplying] = useState(false);
  const [themeOpen, setThemeOpen]   = useState(false);

  useEffect(() => {
    GetGroups().then(setGroups);
  }, []);

  // Apply persisted theme overrides on mount
  useEffect(() => {
    const overrides = loadThemeOverrides();
    Object.entries(overrides).forEach(([name, value]) => applyOverride(name, value));
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
    setBookmarkPdfPath('');
    setBookmarkText('');
    setBookmarkInfo('');
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


  // ── Bookmark editor handlers ───────────────────────────────────────────────
  async function pickBookmarkPdf() {
    const path = await PickFile(['pdf']);
    if (!path) return;
    setBookmarkPdfPath(path);
    setBookmarkText('');
    setBookmarkInfo('');
  }

  async function analyzeBookmarks() {
    if (!bookmarkPdfPath) return;
    setBookmarkAnalyzing(true);
    try {
      const result = await AnalyzeBookmarks(bookmarkPdfPath);
      const headerLines = [
        `# ${result.info || 'Analysis complete.'}`,
        `# Edit below; lines starting with # are ignored on save.`,
        `# Format: page:title (one per line). Blank lines OK.`,
        '',
      ];
      const entryLines = (result.entries || []).map(([page, title]) => `${page}:${title}`);
      setBookmarkText([...headerLines, ...entryLines].join('\n'));
      setBookmarkInfo(result.info || '');
    } catch (e) {
      setBookmarkInfo('Analysis failed: ' + (e?.message || e));
    } finally {
      setBookmarkAnalyzing(false);
    }
  }

  async function applyBookmarks() {
    if (!bookmarkPdfPath || !bookmarkText.trim()) return;
    setBookmarkApplying(true);
    setOutput('');
    setStatus('running');
    // Pass file as positional, list as --pdf_bookmark_add-list <value>
    const args = [bookmarkPdfPath, '--pdf_bookmark_add-list', bookmarkText];
    // We invoke the underlying pdf_bookmark_add op by spoofing the operation field
    // through a synthetic script reference. Easiest: find the PDF Add Bookmarks
    // entry in the registry and call RunScript with it.
    let addGroupIdx = -1, addScriptIdx = -1;
    groups.forEach((g, gi) => {
      g.scripts?.forEach((s, si) => {
        if (s.operation === 'pdf_bookmark_add') { addGroupIdx = gi; addScriptIdx = si; }
      });
    });
    if (addGroupIdx < 0) {
      setOutput('Internal error: pdf_bookmark_add entry missing from registry.');
      setStatus('error');
      setBookmarkApplying(false);
      return;
    }
    const result = await RunScript(addGroupIdx, addScriptIdx, args);
    setOutput(result.output || result.error || '(no output)');
    setStatus(result.error ? 'error' : 'success');
    setBookmarkApplying(false);
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
    setBookmarkPdfPath('');
    setBookmarkText('');
    setBookmarkInfo('');
    setBookmarkAnalyzing(false);
    setBookmarkApplying(false);
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
          <button className="tab tab-icon" onClick={() => setThemeOpen(o => !o)} title="Theme">⚙</button>
        </div>
      </header>
      <ThemePanel open={themeOpen} onClose={() => setThemeOpen(false)} />
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
                  Widget chosen by def.type, falling back to options/text.
                  showWhen: {field, value} hides this widget unless the named
                  arg's current value matches. Lets a dropdown control which
                  related widgets are visible. */}
              {script.argDefs?.map((def, i) => {
                if (def.multiFile) return null;
                if (def.hidden) return null;
                if (def.showWhen) {
                  const targetIdx = script.argDefs.findIndex(
                    d => d.label === def.showWhen.field
                  );
                  if (targetIdx >= 0) {
                    const targetVal = args[targetIdx] ?? script.argDefs[targetIdx].default;
                    if (targetVal !== def.showWhen.value) return null;
                  }
                }

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

                // Textarea (multi-line text input)
                if (def.type === 'textarea') {
                  return (
                    <div key={i} className="arg-group">
                      {label}
                      <div className="arg-row">
                        <textarea
                          className="arg-input arg-textarea"
                          value={args[i] || ''}
                          placeholder={def.placeholder || ''}
                          rows={def.rows || 8}
                          onChange={e => setArg(i, e.target.value)}
                        />
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


                // Bookmark editor — file picker collapses after analysis,
                // textarea fills available space for editing the proposed list.
                if (def.type === 'bookmarkEditor') {
                  const hasAnalyzed = bookmarkText !== '';
                  return (
                    <div key={i} className="bookmark-editor">
                      {!hasAnalyzed && (
                        <div className="bookmark-picker">
                          <div className="arg-label">PDF file</div>
                          <div className="arg-row">
                            <input
                              className="arg-input"
                              value={bookmarkPdfPath}
                              placeholder="No file selected"
                              readOnly
                            />
                            <button className="btn-pick" onClick={pickBookmarkPdf}>
                              Pick PDF
                            </button>
                          </div>
                          <button
                            className="btn-run"
                            onClick={analyzeBookmarks}
                            disabled={!bookmarkPdfPath || bookmarkAnalyzing}
                            style={{ marginTop: 12 }}
                          >
                            {bookmarkAnalyzing ? 'Analyzing…' : 'Analyze'}
                          </button>
                          {bookmarkInfo && !bookmarkAnalyzing && (
                            <div className="bookmark-info">{bookmarkInfo}</div>
                          )}
                        </div>
                      )}
                      {hasAnalyzed && (
                        <>
                          <div className="bookmark-toolbar">
                            <span className="bookmark-file">
                              {bookmarkPdfPath.split('/').pop()}
                            </span>
                            <button
                              className="btn-secondary"
                              onClick={() => { setBookmarkText(''); setBookmarkInfo(''); }}
                            >
                              ← Change PDF
                            </button>
                          </div>
                          <textarea
                            className="arg-input arg-textarea bookmark-textarea"
                            value={bookmarkText}
                            onChange={e => setBookmarkText(e.target.value)}
                            spellCheck={false}
                          />
                        </>
                      )}
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
              {(script.argDefs || []).some(d => d.type === 'bookmarkEditor') ? (
                <button
                  className="btn-run"
                  onClick={applyBookmarks}
                  disabled={!bookmarkText.trim() || bookmarkApplying || status === 'running'}
                >
                  {bookmarkApplying ? 'Applying…' : 'Apply Bookmarks'}
                </button>
              ) : (
                <button
                  className="btn-run"
                  onClick={runScript}
                  disabled={status === 'running'}
                >
                  {status === 'running' ? 'Running…' : 'Run Script'}
                </button>
              )}
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
