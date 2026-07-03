import { Fragment } from 'react';

// Generic widget renderer. Dispatches on def.type; falls back to the
// existing options/text behavior when type is absent.
//
// Skips:
//   - multiFile   (handled by the multi-file queue upstream)
//   - hidden      (flag emitted at runtime, no UI)
//   - bookmarkEditor (self-contained feature component, not a widget)
//
// Honors:
//   - showWhen: { field, value } — hides this widget unless the named
//     arg's current value matches. Lets a dropdown control which
//     related widgets are visible.
export default function WidgetRenderer({ argDefs, args, setArg, pickFile, pickFolder }) {
  if (!argDefs) return null;

  return (
    <>
      {argDefs.map((def, i) => {
        if (def.multiFile) return null;
        if (def.hidden) return null;

        if (def.showWhen) {
          const targetIdx = argDefs.findIndex(d => d.label === def.showWhen.field);
          if (targetIdx >= 0) {
            const targetVal = args[targetIdx] ?? argDefs[targetIdx].default;
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

        // Textarea
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

        // Output directory picker
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

        // Default: dropdown if options, else text input
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
    </>
  );
}
