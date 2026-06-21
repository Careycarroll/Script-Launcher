import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import * as pty from 'node-pty';
import { platform } from 'os';
import path from 'path';
import { execFile, spawn } from 'child_process';
import fs from 'fs';

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
    const flags: string[] = [];
    const positional: string[] = [];
    let workDir = '';

    args.forEach((arg, i) => {
      if (!arg) return;
      const def = script.argDefs?.[i];
      if (def?.setWorkDir && fs.statSync(arg).isDirectory()) {
        workDir = arg;
      } else if (def?.flag) {
        flags.push(def.flag, arg);
      } else {
        positional.push(arg);
      }
    });

    const allArgs = [...flags, ...positional];
    const proc = spawn(script.path, allArgs, {
      env: { ...process.env },
      cwd: workDir || undefined,
    });

    let output = '';
    proc.stdout.on('data', (d: Buffer) => output += d.toString());
    proc.stderr.on('data', (d: Buffer) => output += d.toString());
    proc.on('close', (code: number) => {
      resolve(code === 0 ? { output } : { output, error: `exit status ${code}` });
    });
  });
});

ipcMain.handle('pick-file', async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, { properties: ['openFile'] });
  return result.canceled ? '' : result.filePaths[0];
});

// ── PTY handlers ─────────────────────────────────────────────────────────
let activePty: pty.IPty | null = null;

ipcMain.handle('pty-create', (event, scriptPath: string) => {
  const shell = platform() === 'win32' ? 'powershell.exe' : (process.env.SHELL || '/bin/zsh');
  const env = {
    ...process.env,
    PATH: `/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
    TERM: 'xterm-256color',
  };

  if (activePty) {
    activePty.kill();
    activePty = null;
  }

  activePty = pty.spawn(shell, ['-c', scriptPath], {
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
