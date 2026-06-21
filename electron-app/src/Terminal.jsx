import { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';
import 'xterm/css/xterm.css';

export default function TerminalPanel() {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);

  useEffect(() => {
    // ── Init terminal ───────────────────────────────────────────────────────
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'SF Mono', 'Fira Code', monospace",
      theme: {
        background: '#0d1117',
        foreground: '#c0caf5',
        cursor:     '#4B9CD3',
        black:      '#4a5568',
        blue:       '#4B9CD3',
        cyan:       '#7dcfff',
        green:      '#9ece6a',
        magenta:    '#bb9af7',
        red:        '#f7768e',
        white:      '#c0caf5',
        yellow:     '#ff9e64',
      },
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();

    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current = fitAddon;

    // ── PTY output → terminal ───────────────────────────────────────────────
    window.electronAPI.onPtyOutput((data) => {
      term.write(data);
    });

    window.electronAPI.onPtyExit(() => {
      term.writeln('\r\n\x1b[33m[Process exited]\x1b[0m');
    });

    // ── Terminal input → PTY ────────────────────────────────────────────────
    term.onData((data) => {
      window.electronAPI.PtyInput(data);
    });

    // ── Resize ──────────────────────────────────────────────────────────────
    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      window.electronAPI.PtyResize(term.cols, term.rows);
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      window.electronAPI.offPtyOutput();
      window.electronAPI.offPtyExit();
      term.dispose();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', padding: '8px', boxSizing: 'border-box' }}
    />
  );
}
