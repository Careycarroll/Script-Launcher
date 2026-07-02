import { useState, useImperativeHandle, forwardRef } from 'react';

const { PickFile, RunScript, AnalyzeBookmarks } = window.electronAPI;

// Bespoke bookmark editor. Owns its own state and IPC calls; reports
// run status to the parent via onStatusChange / onOutput so the shared
// output panel and status badge stay in sync.
//
// Exposes an imperative `apply()` method via ref so the parent's
// "Apply Bookmarks" button (in the detail footer) can trigger this
// component's apply flow without lifting all the state up.
//
// Parent is responsible for:
//   - Rendering the footer button that calls ref.current.apply()
//   - Rendering the output panel (from onOutput)
//   - Rendering the status badge (from onStatusChange)
const BookmarkEditor = forwardRef(function BookmarkEditor(
  { groups, onStatusChange, onOutput, onCanApplyChange },
  ref
) {
  const [pdfPath, setPdfPath] = useState('');
  const [text, setText] = useState('');
  const [info, setInfo] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [applying, setApplying] = useState(false);

  const hasAnalyzed = text !== '';

  // Keep parent informed about whether Apply is currently possible.
  function updateCanApply(nextText, nextApplying) {
    onCanApplyChange?.(!!nextText.trim() && !nextApplying);
  }

  async function pickPdf() {
    const path = await PickFile(['pdf']);
    if (!path) return;
    setPdfPath(path);
    setText('');
    setInfo('');
    updateCanApply('', false);
  }

  async function analyze() {
    if (!pdfPath) return;
    setAnalyzing(true);
    try {
      const result = await AnalyzeBookmarks(pdfPath);
      const headerLines = [
        `# ${result.info || 'Analysis complete.'}`,
        `# Edit below; lines starting with # are ignored on save.`,
        `# Format: page:title (one per line). Blank lines OK.`,
        '',
      ];
      const entryLines = (result.entries || []).map(([page, title]) => `${page}:${title}`);
      const nextText = [...headerLines, ...entryLines].join('\n');
      setText(nextText);
      setInfo(result.info || '');
      updateCanApply(nextText, false);
    } catch (e) {
      setInfo('Analysis failed: ' + (e?.message || e));
    } finally {
      setAnalyzing(false);
    }
  }

  async function apply() {
    if (!pdfPath || !text.trim()) return;
    setApplying(true);
    updateCanApply(text, true);
    onOutput?.('');
    onStatusChange?.('running');

    const args = [pdfPath, '--pdf_bookmark_add-list', text];
    let addGroupIdx = -1, addScriptIdx = -1;
    groups.forEach((g, gi) => {
      g.scripts?.forEach((s, si) => {
        if (s.operation === 'pdf_bookmark_add') { addGroupIdx = gi; addScriptIdx = si; }
      });
    });
    if (addGroupIdx < 0) {
      onOutput?.('Internal error: pdf_bookmark_add entry missing from registry.');
      onStatusChange?.('error');
      setApplying(false);
      updateCanApply(text, false);
      return;
    }
    const result = await RunScript(addGroupIdx, addScriptIdx, args);
    onOutput?.(result.output || result.error || '(no output)');
    onStatusChange?.(result.error ? 'error' : 'success');
    setApplying(false);
    updateCanApply(text, false);
  }

  function reset() {
    setPdfPath('');
    setText('');
    setInfo('');
    setAnalyzing(false);
    setApplying(false);
    updateCanApply('', false);
  }

  useImperativeHandle(ref, () => ({ apply, reset, isApplying: () => applying }), [applying, pdfPath, text]);

  return (
    <div className="bookmark-editor">
      {!hasAnalyzed && (
        <div className="bookmark-picker">
          <div className="arg-label">PDF file</div>
          <div className="arg-row">
            <input
              className="arg-input"
              value={pdfPath}
              placeholder="No file selected"
              readOnly
            />
            <button className="btn-pick" onClick={pickPdf}>
              Pick PDF
            </button>
          </div>
          <button
            className="btn-run"
            onClick={analyze}
            disabled={!pdfPath || analyzing}
            style={{ marginTop: 12 }}
          >
            {analyzing ? 'Analyzing…' : 'Analyze'}
          </button>
          {info && !analyzing && (
            <div className="bookmark-info">{info}</div>
          )}
        </div>
      )}
      {hasAnalyzed && (
        <>
          <div className="bookmark-toolbar">
            <span className="bookmark-file">
              {pdfPath.split('/').pop()}
            </span>
            <button
              className="btn-secondary"
              onClick={() => { setText(''); setInfo(''); updateCanApply('', false); }}
            >
              ← Change PDF
            </button>
          </div>
          <textarea
            className="arg-input arg-textarea bookmark-textarea"
            value={text}
            onChange={e => { setText(e.target.value); updateCanApply(e.target.value, applying); }}
            spellCheck={false}
          />
        </>
      )}
    </div>
  );
});

export default BookmarkEditor;
