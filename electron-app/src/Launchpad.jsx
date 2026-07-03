import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
const { GetGroups } = window.electronAPI;

// Launchpad — grid of domain tile cards. Click routes to /{domain}.
// Counts are derived from the registry so cards reflect real content.
// Developer domain is deliberately excluded — reachable via #/developer
// only, not surfaced as a card.
const TILES = [
  {
    domain: 'documents',
    title: 'Documents',
    description: 'PDF, PPTX, and image processing',
    glyph: '📄',
  },
  {
    domain: 'vault',
    title: 'Vault',
    description: 'Obsidian vault management and analysis',
    glyph: '🔑',
  },
  {
    domain: 'media',
    title: 'Media',
    description: 'Audio and video tools',
    glyph: '🎬',
  },
];

export default function Launchpad() {
  const [counts, setCounts] = useState({});

  useEffect(() => {
    GetGroups().then(groups => {
      const c = {};
      groups.forEach(group => {
        (group.scripts || []).forEach(s => {
          const d = s.domain || 'documents';
          c[d] = (c[d] || 0) + 1;
        });
      });
      setCounts(c);
    });
  }, []);

  return (
    <main className="launchpad">
      <div className="launchpad-header">
        <h1 className="launchpad-title">Heelworks</h1>
        <p className="launchpad-subtitle">Personal toolkit — pick a domain</p>
      </div>
      <div className="launchpad-grid">
        {TILES.map(t => (
          <Link to={`/${t.domain}`} key={t.domain} className="launchpad-tile">
            <div className="launchpad-tile-glyph">{t.glyph}</div>
            <div className="launchpad-tile-title">{t.title}</div>
            <div className="launchpad-tile-desc">{t.description}</div>
            <div className="launchpad-tile-count">
              {counts[t.domain] ?? 0} {counts[t.domain] === 1 ? 'script' : 'scripts'}
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}