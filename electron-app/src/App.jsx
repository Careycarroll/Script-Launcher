import { useState, useEffect } from "react";
import { HashRouter, Routes, Route, Link, useLocation, Navigate } from "react-router-dom";
import ThemePanel, { loadThemeOverrides, applyOverride } from "./ThemePanel";
import Launchpad from "./Launchpad";
import DocumentsTile from "./tiles/DocumentsTile";
import VaultTile from "./tiles/VaultTile";
import MediaTile from "./tiles/MediaTile";
import DeveloperTile from "./tiles/DeveloperTile";
import heelworksIcon from "./assets/heelworks-icon.png";
import "./App.css";

// Header — global chrome. Home button hides on the launchpad route.
// Terminal is no longer a global route; interactive scripts render a
// tile-local embedded terminal inside RegistryTile.
function Header({ onThemeToggle }) {
  const location = useLocation();
  const onLaunchpad = location.pathname === "/";

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
        <button className="tab tab-icon" onClick={onThemeToggle} title="Theme">
          ⚙
        </button>
      </div>
    </header>
  );
}

function AppBody() {
  return (
    <div className="app-body" style={{ display: "flex" }}>
      <Routes>
        <Route path="/" element={<Launchpad />} />
        <Route path="/documents" element={<DocumentsTile />} />
        <Route path="/vault" element={<VaultTile />} />
        <Route path="/media" element={<MediaTile />} />
        <Route path="/developer" element={<DeveloperTile />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export default function App() {
  const [themeOpen, setThemeOpen] = useState(false);

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
