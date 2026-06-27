import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Scripts ──────────────────────────────────────────────────────────────
  GetGroups: () => ipcRenderer.invoke('get-groups'),
  RunScript: (groupIdx: number, scriptIdx: number, args: string[]) =>
    ipcRenderer.invoke('run-script', groupIdx, scriptIdx, args),
  PickFile: (extensions?: string[]) => ipcRenderer.invoke('pick-file', extensions),
  PickFolder: () => ipcRenderer.invoke('pick-folder'),
  AnalyzeBookmarks: (pdfPath: string) => ipcRenderer.invoke('analyze-bookmarks', pdfPath),

  // ── PTY / Terminal ────────────────────────────────────────────────────────
  PtyShell: () => ipcRenderer.invoke('pty-shell'),
  PtyCreate: (scriptPath: string, args?: string[]) => ipcRenderer.invoke('pty-create', scriptPath, args || []),
  PtyInput: (data: string) => ipcRenderer.send('pty-input', data),
  PtyResize: (cols: number, rows: number) => ipcRenderer.send('pty-resize', cols, rows),
  PtyKill: () => ipcRenderer.send('pty-kill'),
  onPtyOutput: (cb: (data: string) => void) => {
    ipcRenderer.on('pty-output', (_event, data) => cb(data));
  },
  onPtyExit: (cb: () => void) => {
    ipcRenderer.on('pty-exit', () => cb());
  },
  offPtyOutput: () => ipcRenderer.removeAllListeners('pty-output'),
  offPtyExit: () => ipcRenderer.removeAllListeners('pty-exit'),
});
