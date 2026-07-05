import { useState, useEffect, useRef } from "react";
const {
  StreamStart,
  StreamInput,
  StreamStop,
  onStreamLine,
  onStreamExit,
  offStreamLine,
  offStreamExit,
  PickFolder,
  OpenExternal,
  ListDir,
} = window.electronAPI;

const OUT_DIR_KEY = "panopto-out-dir";
const BROWSER_KEY = "panopto-browser";

const BROWSERS = [
  { value: "zen", label: "Zen" },
  { value: "firefox", label: "Firefox" },
  { value: "chrome", label: "Chrome" },
  { value: "safari", label: "Safari" },
  { value: "brave", label: "Brave" },
  { value: "edge", label: "Edge" },
  { value: "none", label: "None" },
];

const QUALITIES = ["best", "1080p", "720p"];

// Alternative to right-click workflow: paste this into Canvas DevTools Console.
const CANVAS_CONSOLE_SNIPPET =
  `copy(document.querySelector('meta[property="og:url"]')?.content || 'not found')`;

function isPanoptoUrl(s) {
  if (!s) return false;
  return /^https?:\/\/.*\.panopto\.com/i.test(s);
}

function formatBytes(n) {
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(1)} ${units[i]}`;
}

function formatEta(seconds) {
  if (!seconds || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function PanoptoDownloader() {
  const [url, setUrl] = useState("");
  const [outDir, setOutDir] = useState(
    () => localStorage.getItem(OUT_DIR_KEY) || "",
  );
  const [prefix, setPrefix] = useState("01");
  const [quality, setQuality] = useState("best");
  const [captions, setCaptions] = useState(true);
  const [embedSubs, setEmbedSubs] = useState(true);
  const [browser, setBrowser] = useState(
    () => localStorage.getItem(BROWSER_KEY) || "zen",
  );

  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [logs, setLogs] = useState([]);
  const [conflict, setConflict] = useState(null);
  const [result, setResult] = useState(null);

  const logRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(OUT_DIR_KEY, outDir);
  }, [outDir]);
  useEffect(() => {
    localStorage.setItem(BROWSER_KEY, browser);
  }, [browser]);

  // Auto-detect next NN. prefix whenever outDir changes. Scans the folder,
  // finds the max leading number across all filenames, adds 1, zero-pads.
  useEffect(() => {
    if (!outDir) return;
    ListDir(outDir).then((entries) => {
      if (!Array.isArray(entries)) return;
      let maxN = 0;
      for (const name of entries) {
        const m = name.match(/^(\d+)\.\s/);
        if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
      }
      setPrefix((maxN + 1).toString().padStart(2, "0"));
    }).catch(() => { /* ignore; user can still type manually */ });
  }, [outDir]);

  useEffect(() => {
    navigator.clipboard
      .readText()
      .then((text) => {
        if (isPanoptoUrl(text) && !url) setUrl(text.trim());
      })
      .catch(() => {
        /* clipboard permission denied, ignore */
      });
  }, []);

  function appendLog(msg) {
    setLogs((l) => [...l.slice(-100), msg]);
    setTimeout(() => {
      if (logRef.current)
        logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 0);
  }

  async function copyConsoleSnippet() {
    try {
      await navigator.clipboard.writeText(CANVAS_CONSOLE_SNIPPET);
      appendLog('Console snippet copied. Paste into DevTools Console on the Panopto page.');
    } catch (e) {
      appendLog(`✗ Copy failed: ${e.message || e}`);
    }
  }

  async function pickOutDir() {
    const p = await PickFolder();
    if (p) setOutDir(p);
  }

  async function startDownload() {
    if (!url || !outDir || !prefix) return;
    setDownloading(true);
    setProgress(null);
    setLogs([]);
    setConflict(null);
    setResult(null);

    const args = [
      url,
      "--out-dir",
      outDir,
      "--prefix",
      prefix,
      "--quality",
      quality,
      "--browser",
      browser,
      captions ? "--captions" : "--no-captions",
      embedSubs ? "--embed-subs" : "--no-embed-subs",
    ];

    onStreamLine((msg) => {
      if (msg.type === "info") {
        appendLog(msg.message);
      } else if (msg.type === "progress") {
        setProgress(msg);
      } else if (msg.type === "conflict") {
        setConflict(msg);
      } else if (msg.type === "done") {
        setResult({ path: msg.path });
        appendLog(`✓ Saved: ${msg.path}`);
      } else if (msg.type === "error") {
        appendLog(`✗ ${msg.message}`);
      }
    });

    onStreamExit(() => {
      setDownloading(false);
      offStreamLine();
      offStreamExit();
    });

    await StreamStart({ script: "python/scripts/panopto_download.py", args });
  }

  async function respondToConflict(action) {
    await StreamInput({ action });
    setConflict(null);
    if (action === "cancel") {
      appendLog("Cancelled.");
    }
  }

  async function cancel() {
    await StreamStop();
    setDownloading(false);
    appendLog("Stopped.");
  }

  async function revealInFinder() {
    if (result?.path) {
      const parent = result.path.substring(0, result.path.lastIndexOf("/"));
      await OpenExternal(`file://${encodeURI(parent)}`);
    }
  }

  const bar = progress?.percent ?? 0;

  return (
    <div className="panopto-downloader">
      <div className="panopto-header">
        <h2 className="panopto-title">Panopto Downloader</h2>
        <div className="panopto-subtitle">
          Paste a Panopto viewer or embed URL. On a Canvas page, right-click the
          video → "Open Frame in New Tab" → copy the URL from the new tab.
        </div>
      </div>

      <div className="panopto-form">
        <div className="panopto-field">
          <label className="panopto-label">URL</label>
          <div className="panopto-row">
            <input
              className="panopto-input"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://*.panopto.com/Panopto/Pages/... (Viewer or Embed URL)"
              disabled={downloading}
            />
            <button
              className="btn-secondary"
              onClick={copyConsoleSnippet}
              title="Copy a JS snippet for DevTools Console (alternative to right-click workflow)"
              disabled={downloading}
            >
              Copy snippet
            </button>
          </div>
          <div className="panopto-hint">
            Clipboard auto-detects Panopto URLs on tile visit. "Copy snippet" is a fallback for pages where right-click isn't available.
          </div>
        </div>

        <div className="panopto-field">
          <label className="panopto-label">Output folder</label>
          <div className="panopto-row">
            <input
              className="panopto-input"
              value={outDir}
              placeholder="Pick a folder…"
              readOnly
            />
            <button
              className="btn-secondary"
              onClick={pickOutDir}
              disabled={downloading}
            >
              Pick
            </button>
          </div>
        </div>

        <div className="panopto-grid">
          <div className="panopto-field">
            <label className="panopto-label">Number prefix</label>
            <input
              className="panopto-input"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="01"
              disabled={downloading}
              style={{ width: 80 }}
            />
          </div>

          <div className="panopto-field">
            <label className="panopto-label">Quality</label>
            <select
              className="panopto-input"
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
              disabled={downloading}
            >
              {QUALITIES.map((q) => (
                <option key={q} value={q}>
                  {q}
                </option>
              ))}
            </select>
          </div>

          <div className="panopto-field">
            <label className="panopto-label">Cookies from</label>
            <select
              className="panopto-input"
              value={browser}
              onChange={(e) => setBrowser(e.target.value)}
              disabled={downloading}
            >
              {BROWSERS.map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="panopto-checks">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={captions}
              onChange={(e) => setCaptions(e.target.checked)}
              disabled={downloading}
            />
            <span>Download captions (.vtt)</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={embedSubs}
              onChange={(e) => setEmbedSubs(e.target.checked)}
              disabled={downloading || !captions}
            />
            <span>Embed captions in video</span>
          </label>
        </div>

        <div className="panopto-actions">
          {!downloading && (
            <button
              className="btn-run"
              onClick={startDownload}
              disabled={!url || !outDir || !prefix}
            >
              Download
            </button>
          )}
          {downloading && !conflict && (
            <button className="btn-secondary" onClick={cancel}>
              Cancel
            </button>
          )}
        </div>

        {progress && !conflict && (
          <div className="panopto-progress">
            <div className="panopto-progress-bar-wrap">
              <div
                className="panopto-progress-bar"
                style={{ width: `${bar}%` }}
              />
            </div>
            <div className="panopto-progress-stats">
              <span>{bar.toFixed(1)}%</span>
              <span>·</span>
              <span>
                {formatBytes(progress.downloaded_bytes)} /{" "}
                {formatBytes(progress.total_bytes)}
              </span>
              <span>·</span>
              <span>{formatBytes(progress.speed_bps)}/s</span>
              <span>·</span>
              <span>ETA {formatEta(progress.eta_seconds)}</span>
            </div>
          </div>
        )}

        {conflict && (
          <div className="panopto-conflict">
            <div className="panopto-conflict-message">{conflict.message}</div>
            <div className="panopto-conflict-actions">
              <button
                className="btn-run"
                onClick={() => respondToConflict("cancel")}
              >
                Cancel
              </button>
              <button
                className="btn-secondary"
                onClick={() => respondToConflict("overwrite")}
              >
                Overwrite
              </button>
              <button
                className="btn-secondary"
                onClick={() => respondToConflict("increment")}
              >
                Use next number
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="panopto-result">
            <div className="panopto-result-message">
              ✓ Downloaded to {result.path}
            </div>
            <button className="btn-secondary" onClick={revealInFinder}>
              Show in Finder
            </button>
          </div>
        )}
      </div>

      <div className="panopto-log-section">
        <div className="panopto-log-label">Log</div>
        <div className="panopto-log" ref={logRef}>
          {logs.map((l, i) => (
            <div key={i} className="panopto-log-line">
              {l}
            </div>
          ))}
          {logs.length === 0 && <div className="panopto-log-empty">Ready.</div>}
        </div>
      </div>
    </div>
  );
}
