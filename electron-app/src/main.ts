import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import * as pty from 'node-pty';
import { platform } from 'os';
import path from 'path';
import { execFile, spawn } from 'child_process';
import fs from 'fs';

// ── Bundled binary path ───────────────────────────────────────────────────────
const bundledBin = app.isPackaged
  ? path.join(process.resourcesPath, 'bin')
  : path.join(app.getAppPath(), 'resources', 'bin');

// Root for bundled resources (python venv, python scripts, etc.)
// Registry entries with runtime: "python" use paths relative to this root,
// e.g. "python/scripts/docpipe.py" -> <bundledResources>/python/scripts/docpipe.py
const bundledResources = app.isPackaged
  ? process.resourcesPath
  : path.join(app.getAppPath(), 'resources');

const bundledPython = path.join(bundledResources, 'python', 'venv', 'bin', 'python3');

process.env.PATH = `${bundledBin}:${process.env.PATH}`;

// ── Registry ──────────────────────────────────────────────────────────────────
const registryPath = path.join(app.getAppPath(), 'registry.json');
const groups = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));

// ── Window ────────────────────────────────────────────────────────────────────
declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    title: 'Script Launcher',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    win.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ── IPC Handlers ──────────────────────────────────────────────────────────────

ipcMain.handle('get-groups', () => groups);

ipcMain.handle('run-script', (_event, groupIdx: number, scriptIdx: number, args: string[]) => {
  const script = groups[groupIdx]?.scripts[scriptIdx];
  if (!script) return { error: 'Script not found' };

  if (script.interactive) {
    const cmdFile = '/tmp/run_script.command';
    const content = '#!/bin/bash\n' +
      'export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin\n' +
      script.path + '\n';
    fs.writeFileSync(cmdFile, content, { mode: 0o755 });
    execFile('open', [cmdFile]);
    return { output: 'Launched in Terminal' };
  }

  return new Promise((resolve) => {
    // Args arrive fully prepared from renderer (flags already attached to
    // their values). Spawn verbatim — no index-based reconstruction here.
    const allArgs = args.filter(a => a !== '' && a != null);

    // Runtime dispatch:
    //   runtime: "python" -> spawn bundled python with resolved script path as first arg
    //   default           -> spawn script.path directly (legacy / native executables)
    let cmd: string;
    let cmdArgs: string[];
    if (script.runtime === 'python') {
      cmd = bundledPython;
      const opArg = script.operation ? [script.operation] : [];
      cmdArgs = [path.join(bundledResources, script.path), ...opArg, ...allArgs];
    } else {
      cmd = script.path;
      cmdArgs = allArgs;
    }

    const proc = spawn(cmd, cmdArgs, {
      env: { ...process.env },
    });

    let output = '';
    proc.stdout.on('data', (d: Buffer) => output += d.toString());
    proc.stderr.on('data', (d: Buffer) => output += d.toString());
    proc.on('close', (code: number) => {
      resolve(code === 0 ? { output } : { output, error: `exit status ${code}` });
    });
  });
});

ipcMain.handle('pick-file', async (event, extensions?: string[]) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const filters = extensions && extensions.length > 0
    ? [{ name: 'Allowed', extensions }]
    : undefined;
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters,
  });
  return result.canceled ? '' : result.filePaths[0];
});

// ── PTY handlers ─────────────────────────────────────────────────────────
let activePty: pty.IPty | null = null;

ipcMain.handle('pty-shell', (event) => {
  const shell = platform() === 'win32' ? 'powershell.exe' : (process.env.SHELL || '/bin/zsh');
  const env = {
    ...process.env,
    PATH: `${bundledBin}:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
    TERM: 'xterm-256color',
  };

  if (activePty) {
    activePty.kill();
    activePty = null;
  }

  activePty = pty.spawn(shell, [], {
    name: 'xterm-256color',
    cols: 120,
    rows: 40,
    env,
  });

  const win = BrowserWindow.fromWebContents(event.sender);

  activePty.onData((data) => {
    win?.webContents.send('pty-output', data);
  });

  activePty.onExit(() => {
    win?.webContents.send('pty-exit');
    activePty = null;
  });

  return true;
});

ipcMain.handle('pty-create', (event, scriptPath: string, args: string[] = []) => {
  const shell = platform() === 'win32' ? 'powershell.exe' : (process.env.SHELL || '/bin/zsh');
  const env = {
    ...process.env,
    PATH: `${bundledBin}:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
    TERM: 'xterm-256color',
  };

  if (activePty) {
    activePty.kill();
    activePty = null;
  }

  // Shell-quote each arg (single-quote, escape embedded single quotes)
  const shellQuote = (a: string) => `'${a.replace(/'/g, `'\''`)}'`;
  const cmdline = [scriptPath, ...args.map(shellQuote)].join(' ');

  activePty = pty.spawn(shell, ['-c', cmdline], {
    name: 'xterm-256color',
    cols: 120,
    rows: 40,
    env,
  });

  const win = BrowserWindow.fromWebContents(event.sender);

  activePty.onData((data) => {
    win?.webContents.send('pty-output', data);
  });

  activePty.onExit(() => {
    win?.webContents.send('pty-exit');
    activePty = null;
  });

  return true;
});

ipcMain.on('pty-input', (_event, data: string) => {
  activePty?.write(data);
});

ipcMain.on('pty-resize', (_event, cols: number, rows: number) => {
  activePty?.resize(cols, rows);
});

ipcMain.on('pty-kill', () => {
  activePty?.kill();
  activePty = null;
});

ipcMain.handle('pick-folder', async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
  return result.canceled ? '' : result.filePaths[0];
});

// Analyze PDF for bookmark candidates — runs docpipe.py pdf_bookmark_analyze
// and parses the JSON output. Returns { source, entries, info } to renderer.
ipcMain.handle('analyze-bookmarks', (_event, pdfPath: string) => {
  return new Promise((resolve) => {
    const docpipePath = path.join(bundledResources, 'python/scripts/docpipe.py');
    const proc = spawn(bundledPython, [docpipePath, 'pdf_bookmark_analyze', pdfPath], {
      env: { ...process.env },
    });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (d: Buffer) => stdout += d.toString());
    proc.stderr.on('data', (d: Buffer) => stderr += d.toString());
    proc.on('close', (code: number) => {
      if (code !== 0) {
        resolve({ source: 'error', entries: [], info: stderr.trim() || 'Analysis failed.' });
        return;
      }
      // docpipe also prints final output paths on stdout (one per line). The JSON
      // is on its own line. Find the line that parses as JSON.
      const lines = stdout.split('\n').filter(l => l.trim());
      for (const line of lines.reverse()) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.source !== undefined) {
            resolve(parsed);
            return;
          }
        } catch {}
      }
      resolve({ source: 'error', entries: [], info: 'No JSON in analyzer output.' });
    });
  });
});
