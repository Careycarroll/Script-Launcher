import { useState } from 'react';

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

export function loadThemeOverrides() {
  try { return JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) || '{}'); }
  catch { return {}; }
}

export function applyOverride(name, value) {
  document.documentElement.style.setProperty(name, value);
}

export function clearOverride(name) {
  document.documentElement.style.removeProperty(name);
}

export default function ThemePanel({ open, onClose }) {
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
