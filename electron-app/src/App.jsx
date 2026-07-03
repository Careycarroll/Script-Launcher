import { useState, useEffect } from "react";
import {
  HashRouter,
  Routes,
  Route,
  Link,
  useLocation,
  Navigate,
} from "react-router-dom";
import ThemePanel, { loadThemeOverrides, applyOverride } from "./ThemePanel";
import TerminalPanel from "./Terminal";
import Launchpad from "./Launchpad";
import DocumentsTile from "./tiles/DocumentsTile";
import VaultTile from "./tiles/VaultTile";
import MediaTile from "./tiles/MediaTile";
import DeveloperTile from "./tiles/DeveloperTile";
import heelworksIcon from "./assets/heelworks-icon.png";
import "./App.css";

// Header — global chrome. Home button hides on the launchpad route.
// Terminal button routes to /terminal which toggles the always-mounted
// TerminalPanel into visibility (see AppBody below).
function Header({ onThemeToggle }) {
  const location = useLocation();
  const onLaunchpad = location.pathname === "/";
  const onTerminal = location.pathname === "/terminal";

  return (
    <header className="tab-bar">
      <Link to="/" className="tab-bar-title" style={{ textDecoration: "none" }}>
        <img src={heelworksIcon} alt="" className="tab-bar-icon" />
        Heelworks
      </Link>
      <div className="tabs">
        {!onLaunchpad && (
          <Link to="/" className="tab">
            ← Home
          </Link>
        )}
        <Link
          to={onTerminal ? "/" : "/terminal"}
          className={`tab ${onTerminal ? "active" : ""}`}
        >
          Terminal
        </Link>
        <button className="tab tab-icon" onClick={onThemeToggle} title="Theme">
          ⚙
        </button>
      </div>
    </header>
  );
}

// AppBody — renders the current route's tile AND keeps the terminal panel
// always mounted (visibility toggled by CSS). Mounting terminal on-demand
// would kill any running PTY every time the user navigated away.
function AppBody() {
  const location = useLocation();
  const showTerminal = location.pathname === "/terminal";

  return (
    <>
      <div
        className="app-body"
        style={{ display: showTerminal ? "none" : "flex" }}
      >
        <Routes>
          <Route path="/" element={<Launchpad />} />
          <Route path="/documents" element={<DocumentsTile />} />
          <Route path="/vault" element={<VaultTile />} />
          <Route path="/media" element={<MediaTile />} />
          <Route path="/developer" element={<DeveloperTile />} />
          <Route path="/terminal" element={null} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <div
        className="terminal-tab"
        style={{ display: showTerminal ? "flex" : "none" }}
      >
        <TerminalPanel />
      </div>
    </>
  );
}

export default function App() {
  const [themeOpen, setThemeOpen] = useState(false);

  // Apply persisted theme overrides on mount, before first paint.
  useEffect(() => {
    const overrides = loadThemeOverrides();
    Object.entries(overrides).forEach(([name, value]) =>
      applyOverride(name, value),
    );
  }, []);

  return (
    <HashRouter>
      <div className="app-wrapper">
        <Header onThemeToggle={() => setThemeOpen((o) => !o)} />
        <ThemePanel open={themeOpen} onClose={() => setThemeOpen(false)} />
        <AppBody />
      </div>
    </HashRouter>
  );
}
