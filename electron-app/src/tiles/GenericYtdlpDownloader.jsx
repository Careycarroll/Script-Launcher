import { useState, useEffect, useMemo, useRef } from "react";
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

const OUT_DIR_KEY = "generic-ytdlp-out-dir";
const BROWSER_KEY = "generic-ytdlp-browser";

const BROWSERS = [
  { value: "none", label: "None" },
  { value: "zen", label: "Zen" },
  { value: "firefox", label: "Firefox" },
  { value: "chrome", label: "Chrome" },
  { value: "safari", label: "Safari" },
  { value: "brave", label: "Brave" },
  { value: "edge", label: "Edge" },
];

const QUALITIES = ["best", "1080p", "720p", "audio"];
const AUDIO_FORMATS = ["original", "mp3", "m4a"];
const CONTAINERS = [
  { value: "auto", label: "Auto / source" },
  { value: "mkv", label: "MKV" },
  { value: "mp4", label: "MP4" },
  { value: "webm", label: "WebM" },
];

export function isLikelyUrl(s) {
  return /^https?:\/\//i.test(s || "");
}

export function looksLikePlaylistUrl(s) {
  const u = (s || "").toLowerCase();
  return (
    u.includes("list=") ||
    u.includes("/playlist") ||
    u.includes("playlist") ||
    u.includes("/sets/") ||
    u.includes("/album/") ||
    u.includes("/channel/") ||
    u.includes("/@")
  );
}

function formatBytes(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "";
  if (n === 0) return "0 B";
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

function formatDuration(seconds) {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    : `${m}:${s.toString().padStart(2, "0")}`;
}

export function compactIndexes(indexes) {
  const xs = [...new Set(indexes.map((x) => Number(x)).filter(Boolean))].sort(
    (a, b) => a - b,
  );
  if (xs.length === 0) return "";
  const ranges = [];
  let start = xs[0];
  let prev = xs[0];
  for (const x of xs.slice(1)) {
    if (x === prev + 1) {
      prev = x;
    } else {
      ranges.push(start === prev ? `${start}` : `${start}-${prev}`);
      start = prev = x;
    }
  }
  ranges.push(start === prev ? `${start}` : `${start}-${prev}`);
  return ranges.join(",");
}

export default function GenericYtdlpDownloader() {
  const [url, setUrl] = useState("");
  const [outDir, setOutDir] = useState(
    () => localStorage.getItem(OUT_DIR_KEY) || "",
  );
  const [usePrefix, setUsePrefix] = useState(false);
  const [prefix, setPrefix] = useState("01");
  const [quality, setQuality] = useState("best");
  const [audioFormat, setAudioFormat] = useState("original");
  const [container, setContainer] = useState("auto");
  const [recodeVideo, setRecodeVideo] = useState(false);
  const [captions, setCaptions] = useState(false);
  const [autoCaptions, setAutoCaptions] = useState(false);
  const [subLangs, setSubLangs] = useState("en");
  const [embedSubs, setEmbedSubs] = useState(false);
  const [embedThumbnail, setEmbedThumbnail] = useState(false);
  const [browser, setBrowser] = useState(
    () => localStorage.getItem(BROWSER_KEY) || "none",
  );
  const [allowPlaylist, setAllowPlaylist] = useState(false);
  const [playlistItems, setPlaylistItems] = useState("");
  const [concurrentFragments, setConcurrentFragments] = useState("4");
  const [retries, setRetries] = useState("10");
  const [fragmentRetries, setFragmentRetries] = useState("10");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [logs, setLogs] = useState([]);
  const [conflict, setConflict] = useState(null);
  const [result, setResult] = useState(null);
  const [metadata, setMetadata] = useState(null);
  const [editedTitle, setEditedTitle] = useState("");
  const [selectedPlaylistItems, setSelectedPlaylistItems] = useState(new Set());

  const logRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(OUT_DIR_KEY, outDir);
  }, [outDir]);
  useEffect(() => {
    localStorage.setItem(BROWSER_KEY, browser);
  }, [browser]);

  useEffect(() => {
    if (!outDir) return;
    ListDir(outDir)
      .then((entries) => {
        if (!Array.isArray(entries)) return;
        let maxN = 0;
        for (const name of entries) {
          const m = name.match(/^(\d+)\.\s/);
          if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
        }
        setPrefix((maxN + 1).toString().padStart(2, "0"));
      })
      .catch(() => {});
  }, [outDir]);

  useEffect(() => {
    navigator.clipboard
      .readText()
      .then((text) => {
        if (isLikelyUrl(text) && !url) {
          setUrl(text.trim());
          if (looksLikePlaylistUrl(text)) setAllowPlaylist(true);
        }
      })
      .catch(() => {});
  }, []);

  const playlistEntries = metadata?.playlist_preview || [];
  const selectedCount = selectedPlaylistItems.size;

  const selectedPlaylistItemsString = useMemo(() => {
    return compactIndexes([...selectedPlaylistItems]);
  }, [selectedPlaylistItems]);

  function appendLog(msg) {
    setLogs((l) => [...l.slice(-100), msg]);
    setTimeout(() => {
      if (logRef.current)
        logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 0);
  }

  function handleUrlChange(next) {
    setUrl(next);
    if (looksLikePlaylistUrl(next)) setAllowPlaylist(true);
  }

  async function pickOutDir() {
    const p = await PickFolder();
    if (p) setOutDir(p);
  }

  async function startDownload() {
    if (!url || !outDir || (usePrefix && !prefix)) return;
    setDownloading(true);
    setProgress(null);
    setLogs([]);
    setConflict(null);
    setResult(null);
    setMetadata(null);
    setEditedTitle("");
    setSelectedPlaylistItems(new Set());

    const args = [
      url,
      "--out-dir",
      outDir,
      usePrefix ? "--use-prefix" : "--no-use-prefix-placeholder",
      "--prefix",
      prefix,
      "--quality",
      quality,
      "--audio-format",
      audioFormat,
      "--container",
      container,
      recodeVideo ? "--recode-video" : "--no-recode-video-placeholder",
      captions ? "--captions" : "--no-captions",
      autoCaptions ? "--auto-captions" : "--no-auto-captions",
      "--sub-langs",
      subLangs,
      embedSubs ? "--embed-subs" : "--no-embed-subs",
      embedThumbnail ? "--embed-thumbnail" : "--no-embed-thumbnail-placeholder",
      "--browser",
      browser,
      allowPlaylist ? "--allow-playlist" : "--no-allow-playlist-placeholder",
      "--playlist-items",
      playlistItems,
      "--concurrent-fragments",
      String(concurrentFragments || "4"),
      "--retries",
      String(retries || "10"),
      "--fragment-retries",
      String(fragmentRetries || "10"),
    ].filter(
      (a) =>
        a !== "--no-use-prefix-placeholder" &&
        a !== "--no-recode-video-placeholder" &&
        a !== "--no-embed-thumbnail-placeholder" &&
        a !== "--no-allow-playlist-placeholder",
    );

    onStreamLine((msg) => {
      if (msg.type === "info") appendLog(msg.message);
      else if (msg.type === "metadata") {
        setMetadata(msg);
        setEditedTitle(msg.title || "");
        if (msg.is_playlist) {
          setAllowPlaylist(true);
          const indexes = (msg.playlist_preview || []).map((e) => e.index);
          setSelectedPlaylistItems(new Set(indexes));
          appendLog(
            `Playlist detected: ${msg.title} (${msg.playlist_count || "unknown"} items)`,
          );
        } else {
          appendLog(`Found: ${msg.title}`);
        }
      } else if (msg.type === "progress") setProgress(msg);
      else if (msg.type === "conflict") setConflict(msg);
      else if (msg.type === "done") {
        setResult({ path: msg.path });
        appendLog(`✓ Saved: ${msg.path}`);
      } else if (msg.type === "error") appendLog(`✗ ${msg.message}`);
    });

    onStreamExit(() => {
      setDownloading(false);
      offStreamLine();
      offStreamExit();
    });

    await StreamStart({ script: "python/scripts/ytdlp_download.py", args });
  }

  async function confirmDownload() {
    const payload = {
      action: "confirm",
      title: editedTitle,
      allow_playlist: allowPlaylist,
      playlist_items: metadata?.is_playlist
        ? selectedPlaylistItemsString || playlistItems
        : playlistItems,
    };
    await StreamInput(payload);
    setMetadata(null);
  }

  async function cancelDownload() {
    await StreamInput({ action: "cancel" });
    setMetadata(null);
    setEditedTitle("");
  }

  async function respondToConflict(action) {
    await StreamInput({ action });
    setConflict(null);
    if (action === "cancel") appendLog("Cancelled.");
  }

  async function cancel() {
    await StreamStop();
    setDownloading(false);
    appendLog("Stopped.");
  }

  async function revealInFinder() {
    if (result?.path) {
      const target = result.path.endsWith("/") ? result.path.slice(0, -1) : result.path;
      await OpenExternal(`file://${encodeURI(target)}`);
    }
  }

  function setAllPlaylistItems(selected) {
    if (!metadata?.is_playlist) return;
    setSelectedPlaylistItems(
      selected ? new Set(playlistEntries.map((e) => e.index)) : new Set(),
    );
  }

  function invertPlaylistItems() {
    setSelectedPlaylistItems((prev) => {
      const next = new Set();
      for (const entry of playlistEntries) {
        if (!prev.has(entry.index)) next.add(entry.index);
      }
      return next;
    });
  }

  function togglePlaylistItem(index) {
    setSelectedPlaylistItems((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  const bar = progress?.percent ?? 0;
  const extensionPreview =
    quality === "audio"
      ? audioFormat === "original"
        ? "audio-ext"
        : audioFormat
      : container === "auto"
        ? "ext"
        : container;

  return (
    <div className="generic-ytdlp-downloader panopto-downloader">
      <div className="panopto-header">
        <h2 className="panopto-title">Generic yt-dlp Downloader</h2>
        <div className="panopto-subtitle">
          Paste any yt-dlp-supported media URL. Playlist downloads are reviewed
          before download and selected items preserve source playlist numbering.
        </div>
      </div>

      <div className="panopto-form">
        <div className="panopto-field">
          <label className="panopto-label">URL</label>
          <input
            className="panopto-input"
            value={url}
            onChange={(e) => handleUrlChange(e.target.value)}
            placeholder="https://..."
            disabled={downloading}
          />
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
            <button className="btn-secondary" onClick={pickOutDir} disabled={downloading}>
              Pick
            </button>
          </div>
        </div>

        <div className="generic-ytdlp-section-title">Download scope</div>
        <div className="panopto-checks">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={allowPlaylist}
              onChange={(e) => setAllowPlaylist(e.target.checked)}
              disabled={downloading}
            />
            <span>Allow playlist downloads</span>
          </label>
        </div>
        <div className="panopto-field">
          <label className="panopto-label">Playlist items (optional)</label>
          <input
            className="panopto-input"
            value={playlistItems}
            onChange={(e) => setPlaylistItems(e.target.value)}
            placeholder="all, or e.g. 1-5,8,10"
            disabled={downloading || !allowPlaylist}
          />
          <div className="panopto-hint">
            Playlist output uses one numbering system: original playlist index in a playlist-named subfolder. Preview capped at 100 entries.
          </div>
        </div>

        <div className="generic-ytdlp-section-title">Naming</div>
        <div className="panopto-checks">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={usePrefix}
              onChange={(e) => setUsePrefix(e.target.checked)}
              disabled={downloading}
            />
            <span>Add numeric prefix for single video</span>
          </label>
        </div>
        {usePrefix && (
          <div className="panopto-field generic-prefix-field">
            <label className="panopto-label">Number prefix</label>
            <input
              className="panopto-input"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              disabled={downloading}
              style={{ width: 80 }}
            />
          </div>
        )}

        <div className="generic-ytdlp-section-title">Media format</div>
        <div className="generic-ytdlp-advanced-grid">
          <div className="panopto-field">
            <label className="panopto-label">Quality</label>
            <select
              className="panopto-input"
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
              disabled={downloading}
            >
              {QUALITIES.map((q) => (
                <option key={q} value={q}>{q}</option>
              ))}
            </select>
          </div>
          <div className="panopto-field">
            <label className="panopto-label">Audio format</label>
            <select
              className="panopto-input"
              value={audioFormat}
              onChange={(e) => setAudioFormat(e.target.value)}
              disabled={downloading || quality !== "audio"}
            >
              {AUDIO_FORMATS.map((q) => (
                <option key={q} value={q}>{q}</option>
              ))}
            </select>
          </div>
          <div className="panopto-field">
            <label className="panopto-label">Final container</label>
            <select
              className="panopto-input"
              value={container}
              onChange={(e) => setContainer(e.target.value)}
              disabled={downloading || quality === "audio"}
            >
              {CONTAINERS.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="panopto-checks">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={recodeVideo}
              onChange={(e) => setRecodeVideo(e.target.checked)}
              disabled={downloading || container === "auto" || quality === "audio"}
            />
            <span>Force re-encode if needed</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={embedThumbnail}
              onChange={(e) => setEmbedThumbnail(e.target.checked)}
              disabled={downloading}
            />
            <span>Embed thumbnail / cover art when available</span>
          </label>
        </div>

        <div className="generic-ytdlp-section-title">Captions</div>
        <div className="panopto-checks">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={captions}
              onChange={(e) => setCaptions(e.target.checked)}
              disabled={downloading}
            />
            <span>Download subtitles/captions when available</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={autoCaptions}
              onChange={(e) => setAutoCaptions(e.target.checked)}
              disabled={downloading}
            />
            <span>Allow auto-generated captions</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={embedSubs}
              onChange={(e) => setEmbedSubs(e.target.checked)}
              disabled={downloading || (!captions && !autoCaptions)}
            />
            <span>Embed captions when supported</span>
          </label>
        </div>
        <div className="panopto-field">
          <label className="panopto-label">Subtitle languages</label>
          <input
            className="panopto-input"
            value={subLangs}
            onChange={(e) => setSubLangs(e.target.value)}
            placeholder="en, en-US, all"
            disabled={downloading || (!captions && !autoCaptions)}
          />
        </div>

        <div className="generic-ytdlp-section-title">Authentication</div>
        <div className="panopto-field">
          <label className="panopto-label">Cookies from</label>
          <select
            className="panopto-input"
            value={browser}
            onChange={(e) => setBrowser(e.target.value)}
            disabled={downloading}
          >
            {BROWSERS.map((b) => (
              <option key={b.value} value={b.value}>{b.label}</option>
            ))}
          </select>
        </div>

        <button
          type="button"
          className="generic-ytdlp-advanced-toggle"
          onClick={() => setAdvancedOpen((v) => !v)}
        >
          {advancedOpen ? "▾" : "▸"} Advanced network options
        </button>
        {advancedOpen && (
          <div className="generic-ytdlp-advanced-grid generic-ytdlp-advanced-box">
            <div className="panopto-field">
              <label className="panopto-label">Concurrent fragments</label>
              <input
                className="panopto-input"
                type="number"
                min="1"
                max="16"
                value={concurrentFragments}
                onChange={(e) => setConcurrentFragments(e.target.value)}
                disabled={downloading}
              />
            </div>
            <div className="panopto-field">
              <label className="panopto-label">Retries</label>
              <input
                className="panopto-input"
                type="number"
                min="0"
                max="50"
                value={retries}
                onChange={(e) => setRetries(e.target.value)}
                disabled={downloading}
              />
            </div>
            <div className="panopto-field">
              <label className="panopto-label">Fragment retries</label>
              <input
                className="panopto-input"
                type="number"
                min="0"
                max="50"
                value={fragmentRetries}
                onChange={(e) => setFragmentRetries(e.target.value)}
                disabled={downloading}
              />
            </div>
          </div>
        )}

        <div className="panopto-actions">
          {!downloading && (
            <button
              className="btn-run"
              onClick={startDownload}
              disabled={!url || !outDir || (usePrefix && !prefix)}
            >
              {looksLikePlaylistUrl(url) || allowPlaylist ? "Fetch playlist metadata" : "Fetch metadata"}
            </button>
          )}
          {downloading && !conflict && !metadata && (
            <button className="btn-secondary" onClick={cancel}>Cancel</button>
          )}
        </div>

        {metadata && !metadata.is_playlist && (
          <div className="panopto-metadata">
            <div className="panopto-metadata-label">Review & confirm</div>
            <input
              className="panopto-input panopto-metadata-title-input"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              placeholder="Video title used in filename"
            />
            <div className="panopto-metadata-stats">
              {metadata.width && metadata.height && <span>{metadata.width}×{metadata.height}</span>}
              {metadata.fps && <span>· {metadata.fps} fps</span>}
              {metadata.duration_seconds && <span>· {formatDuration(metadata.duration_seconds)}</span>}
              {metadata.filesize && <span>· ~{formatBytes(metadata.filesize)}</span>}
              {metadata.format_id && <span>· {metadata.format_id}</span>}
            </div>
            <div className="panopto-metadata-preview">
              Will save as: <code>{usePrefix ? `${prefix}. ` : ""}{editedTitle}.{extensionPreview}</code>
            </div>
            <div className="panopto-metadata-actions">
              <button className="btn-run" onClick={confirmDownload} disabled={!editedTitle.trim()}>
                Confirm & download
              </button>
              <button className="btn-secondary" onClick={cancelDownload}>Cancel</button>
            </div>
          </div>
        )}

        {metadata && metadata.is_playlist && (
          <div className="generic-playlist-panel">
            <div className="panopto-metadata-label">Playlist detected</div>
            <div className="generic-playlist-title">{metadata.title}</div>
            <div className="panopto-metadata-stats">
              <span>{metadata.playlist_count || "Unknown"} item{metadata.playlist_count === 1 ? "" : "s"}</span>
              <span>· Preview capped at {metadata.playlist_preview_cap || 100}</span>
              <span>· Selected {selectedCount} / {playlistEntries.length}</span>
            </div>
            <div className="panopto-metadata-preview">
              Will save into: <code>{metadata.title}/01. Title.ext</code>
            </div>
            <div className="generic-playlist-actions">
              <button className="btn-secondary" onClick={() => setAllPlaylistItems(true)}>Select all</button>
              <button className="btn-secondary" onClick={() => setAllPlaylistItems(false)}>Select none</button>
              <button className="btn-secondary" onClick={invertPlaylistItems}>Invert</button>
            </div>
            <div className="generic-playlist-list">
              {playlistEntries.map((entry) => (
                <label key={entry.index} className="generic-playlist-row">
                  <input
                    type="checkbox"
                    checked={selectedPlaylistItems.has(entry.index)}
                    onChange={() => togglePlaylistItem(entry.index)}
                  />
                  <span className="generic-playlist-index">{String(entry.index).padStart(2, "0")}.</span>
                  <span className="generic-playlist-row-title">{entry.title}</span>
                  {entry.duration_seconds && <span className="generic-playlist-duration">{formatDuration(entry.duration_seconds)}</span>}
                </label>
              ))}
              {playlistEntries.length === 0 && (
                <div className="panopto-log-empty">No playlist entries available for preview.</div>
              )}
            </div>
            <div className="panopto-metadata-actions">
              <button
                className="btn-run"
                onClick={confirmDownload}
                disabled={selectedCount === 0}
              >
                Confirm & download selected
              </button>
              <button className="btn-secondary" onClick={cancelDownload}>Cancel</button>
            </div>
          </div>
        )}

        {progress && !conflict && (
          <div className="panopto-progress">
            <div className="panopto-progress-bar-wrap">
              <div className="panopto-progress-bar" style={{ width: `${bar}%` }} />
            </div>
            <div className="panopto-progress-stats">
              <span>{bar.toFixed(1)}%</span><span>·</span>
              <span>{formatBytes(progress.downloaded_bytes)} / {formatBytes(progress.total_bytes)}</span><span>·</span>
              <span>{formatBytes(progress.speed_bps)}/s</span><span>·</span>
              <span>ETA {formatEta(progress.eta_seconds)}</span>
            </div>
          </div>
        )}

        {conflict && (
          <div className="panopto-conflict">
            <div className="panopto-conflict-message">{conflict.message}</div>
            <div className="panopto-conflict-actions">
              <button className="btn-run" onClick={() => respondToConflict("cancel")}>Cancel</button>
              <button className="btn-secondary" onClick={() => respondToConflict("overwrite")}>Overwrite</button>
              <button className="btn-secondary" onClick={() => respondToConflict("increment")}>Use next number</button>
            </div>
          </div>
        )}

        {result && (
          <div className="panopto-result">
            <div className="panopto-result-message">✓ Downloaded to {result.path}</div>
            <button className="btn-secondary" onClick={revealInFinder}>Show in Finder</button>
          </div>
        )}
      </div>

      <div className="panopto-log-section">
        <div className="panopto-log-label">Log</div>
        <div className="panopto-log" ref={logRef}>
          {logs.map((l, i) => <div key={i} className="panopto-log-line">{l}</div>)}
          {logs.length === 0 && <div className="panopto-log-empty">Ready.</div>}
        </div>
      </div>
    </div>
  );
}
