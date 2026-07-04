import { app, BrowserWindow, ipcMain, dialog } from "electron";
import * as pty from "node-pty";
import { platform } from "os";
import path from "path";
import { execFile, spawn, ChildProcess } from "child_process";
import fs from "fs";

// ── Bundled binary path ───────────────────────────────────────────────────────
const bundledBin = app.isPackaged
  ? path.join(process.resourcesPath, "bin")
  : path.join(app.getAppPath(), "resources", "bin");

// Root for bundled resources (python venv, python scripts, etc.)
// Registry entries with runtime: "python" use paths relative to this root,
// e.g. "python/scripts/docpipe.py" -> <bundledResources>/python/scripts/docpipe.py
const bundledResources = app.isPackaged
  ? process.resourcesPath
  : path.join(app.getAppPath(), "resources");

const bundledPython = path.join(
  bundledResources,
  "python",
  "venv",
  "bin",
  "python3",
);

process.env.PATH = `${bundledBin}:${process.env.PATH}`;

// ── Registry ──────────────────────────────────────────────────────────────────
const registryPath = path.join(app.getAppPath(), "registry.json");
const groups = JSON.parse(fs.readFileSync(registryPath, "utf-8"));

// ── Window ────────────────────────────────────────────────────────────────────
declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    title: "Script Launcher",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    win.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`),
    );
  }
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// ── IPC Handlers ──────────────────────────────────────────────────────────────

ipcMain.handle("get-groups", () => groups);

ipcMain.handle(
  "run-script",
  (_event, groupIdx: number, scriptIdx: number, args: string[]) => {
    const script = groups[groupIdx]?.scripts[scriptIdx];
    if (!script) return { error: "Script not found" };

    if (script.interactive) {
      const cmdFile = "/tmp/run_script.command";
      const content =
        "#!/bin/bash\n" +
        "export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin\n" +
        script.path +
        "\n";
      fs.writeFileSync(cmdFile, content, { mode: 0o755 });
      execFile("open", [cmdFile]);
      return { output: "Launched in Terminal" };
    }

    return new Promise((resolve) => {
      // Args arrive fully prepared from renderer (flags already attached to
      // their values). Spawn verbatim — no index-based reconstruction here.
      const allArgs = args.filter((a) => a !== "" && a != null);

      // Runtime dispatch:
      //   runtime: "python" -> spawn bundled python with resolved script path as first arg
      //   default           -> spawn script.path directly (legacy / native executables)
      let cmd: string;
      let cmdArgs: string[];
      if (script.runtime === "python") {
        cmd = bundledPython;
        const opArg = script.operation ? [script.operation] : [];
        cmdArgs = [
          path.join(bundledResources, script.path),
          ...opArg,
          ...allArgs,
        ];
      } else {
        cmd = script.path;
        cmdArgs = allArgs;
      }

      const proc = spawn(cmd, cmdArgs, {
        env: { ...process.env },
      });

      let output = "";
      proc.stdout.on("data", (d: Buffer) => (output += d.toString()));
      proc.stderr.on("data", (d: Buffer) => (output += d.toString()));
      proc.on("close", (code: number) => {
        resolve(
          code === 0 ? { output } : { output, error: `exit status ${code}` },
        );
      });
    });
  },
);

ipcMain.handle("pick-file", async (event, extensions?: string[]) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const filters =
    extensions && extensions.length > 0
      ? [{ name: "Allowed", extensions }]
      : undefined;
  const result = await dialog.showOpenDialog(win, {
    properties: ["openFile"],
    filters,
  });
  return result.canceled ? "" : result.filePaths[0];
});

// ── PTY handlers ─────────────────────────────────────────────────────────
let activePty: pty.IPty | null = null;

ipcMain.handle("pty-shell", (event) => {
  console.log("[pty-shell] START");
  const shell =
    platform() === "win32" ? "powershell.exe" : process.env.SHELL || "/bin/zsh";
  const env = {
    ...process.env,
    PATH: `${bundledBin}:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
    TERM: "xterm-256color",
  };

  if (activePty) {
    const stale = activePty;
    activePty = null;
    stale.kill();
  }

  try {
    activePty = pty.spawn(shell, [], {
      name: "xterm-256color",
      cols: 120,
      rows: 40,
      env,
    });
    console.log("[pty-shell] spawn ok pid=", activePty.pid);
  } catch (err) {
    console.error("[pty-shell] SPAWN FAILED:", err);
    return false;
  }

  const win = BrowserWindow.fromWebContents(event.sender);

  activePty.onData((data) => {
    win?.webContents.send("pty-output", data);
  });

  const thisPty = activePty;
  thisPty.onExit(() => {
    win?.webContents.send("pty-exit");
    if (activePty === thisPty) activePty = null;
  });

  return true;
});

ipcMain.handle(
  "pty-create",
  (event, scriptPath: string, args: string[] = []) => {
    console.log("[pty-create] START", scriptPath, JSON.stringify(args));
    const env = {
      ...process.env,
      PATH: `${bundledBin}:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
      TERM: "xterm-256color",
    };

    if (activePty) {
      // Detach old PTY's ref BEFORE killing so its onExit callback
      // doesn't stomp the new PTY we're about to spawn.
      const stale = activePty;
      activePty = null;
      stale.kill();
    }

    try {
      activePty = pty.spawn(scriptPath, args, {
        name: "xterm-256color",
        cols: 120,
        rows: 40,
        env,
      });
      console.log("[pty-create] spawn ok pid=", activePty.pid);
    } catch (err) {
      console.error("[pty-create] SPAWN FAILED:", err);
      return false;
    }

    const win = BrowserWindow.fromWebContents(event.sender);

    activePty.onData((data) => {
      win?.webContents.send("pty-output", data);
    });

    const thisPty = activePty;
    thisPty.onExit((e) => {
      console.log(
        "[pty-create] exited",
        JSON.stringify(e),
        "script:",
        scriptPath,
      );
      win?.webContents.send("pty-exit");
      if (activePty !== thisPty) return;
      activePty = null;

      // Auto-respawn shell so terminal stays usable after script exits.
      const shell = process.env.SHELL || "/bin/zsh";
      const respawnEnv = {
        ...process.env,
        PATH: `${bundledBin}:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin:${process.env.PATH}`,
        TERM: "xterm-256color",
        PROMPT_EOL_MARK: "",
      };
      try {
        const respawned = pty.spawn(shell, [], {
          name: "xterm-256color",
          cols: 120,
          rows: 40,
          env: respawnEnv,
        });
        activePty = respawned;
        console.log("[pty-create] auto-respawn shell pid=", respawned.pid);
        respawned.onData((data) => win?.webContents.send("pty-output", data));
        respawned.onExit(() => {
          win?.webContents.send("pty-exit");
          if (activePty === respawned) activePty = null;
        });
      } catch (err) {
        console.error("[pty-create] auto-respawn FAILED:", err);
      }
    });

    return true;
  },
);

ipcMain.on("pty-input", (_event, data: string) => {
  console.log(
    "[pty-input] activePty=",
    !!activePty,
    "data=",
    JSON.stringify(data),
  );
  activePty?.write(data);
});

ipcMain.on("pty-resize", (_event, cols: number, rows: number) => {
  activePty?.resize(cols, rows);
});

ipcMain.on("pty-kill", () => {
  activePty?.kill();
  activePty = null;
});

ipcMain.handle("pick-folder", async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    properties: ["openDirectory"],
  });
  return result.canceled ? "" : result.filePaths[0];
});

// Analyze PDF for bookmark candidates — runs docpipe.py pdf_bookmark_analyze
// and parses the JSON output. Returns { source, entries, info } to renderer.
ipcMain.handle("analyze-bookmarks", (_event, pdfPath: string) => {
  return new Promise((resolve) => {
    const docpipePath = path.join(
      bundledResources,
      "python/scripts/docpipe.py",
    );
    const proc = spawn(
      bundledPython,
      [docpipePath, "pdf_bookmark_analyze", pdfPath],
      {
        env: { ...process.env },
      },
    );
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    proc.on("close", (code: number) => {
      if (code !== 0) {
        resolve({
          source: "error",
          entries: [],
          info: stderr.trim() || "Analysis failed.",
        });
        return;
      }
      // docpipe also prints final output paths on stdout (one per line). The JSON
      // is on its own line. Find the line that parses as JSON.
      const lines = stdout.split("\n").filter((l) => l.trim());
      for (const line of lines.reverse()) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.source !== undefined) {
            resolve(parsed);
            return;
          }
        } catch {}
      }
      resolve({
        source: "error",
        entries: [],
        info: "No JSON in analyzer output.",
      });
    });
  });
});

// ── Save file (used by Vault exports) ────────────────────────────────
ipcMain.handle(
  "save-file",
  async (
    event,
    opts: { defaultName: string; content: string; filters?: any[] },
  ) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showSaveDialog(win, {
      defaultPath: opts.defaultName,
      filters: opts.filters || [],
    });
    if (result.canceled || !result.filePath) return { saved: false };
    fs.writeFileSync(result.filePath, opts.content, "utf-8");
    return { saved: true, path: result.filePath };
  },
);

// ── Open external URL (obsidian://, https://, etc.) ──────────────────
ipcMain.handle("open-external", async (_e, url: string) => {
  const { shell } = await import("electron");
  await shell.openExternal(url);
  return { opened: true };
});

// ── Vault Workbench IPC ────────────────────────────────────────────────
// Long-lived vault_index.py --serve process. One per app lifetime.
// Requests are matched to responses by 'id' echoed back in the JSON.
let vaultProc: ChildProcess | null = null;
let vaultBuffer = "";
const vaultPending = new Map<
  string,
  { resolve: (v: any) => void; reject: (e: Error) => void }
>();

function killVaultProc() {
  if (vaultProc) {
    vaultProc.kill();
    vaultProc = null;
  }
  vaultBuffer = "";
  vaultPending.forEach((p) => p.reject(new Error("vault process terminated")));
  vaultPending.clear();
}

ipcMain.handle("vault-start", async (_e, vaultPath: string) => {
  if (vaultProc) killVaultProc();

  const pythonPath = bundledPython; // reuse your existing helper
  const scriptPath = path.join(
    bundledResources,
    "python/scripts/vault_index.py",
  );

  vaultProc = spawn(pythonPath, [scriptPath, vaultPath, "--serve"], {
    stdio: ["pipe", "pipe", "pipe"],
  });

  vaultProc.stdout?.on("data", (chunk: Buffer) => {
    vaultBuffer += chunk.toString("utf8");
    let idx: number;
    while ((idx = vaultBuffer.indexOf("\n")) >= 0) {
      const line = vaultBuffer.slice(0, idx).trim();
      vaultBuffer = vaultBuffer.slice(idx + 1);
      if (!line) continue;
      try {
        const msg = JSON.parse(line);
        const pending = vaultPending.get(msg.id);
        if (pending) {
          vaultPending.delete(msg.id);
          if (msg.error)
            pending.reject(
              new Error(`${msg.error.code}: ${msg.error.message}`),
            );
          else pending.resolve(msg.result);
        }
      } catch {
        // Ignore malformed lines; not our problem.
      }
    }
  });

  vaultProc.stderr?.on("data", (chunk: Buffer) => {
    // Log to console so devs can see; not surfaced to renderer.
    process.stderr.write(`[vault_index] ${chunk.toString("utf8")}`);
  });

  vaultProc.on("exit", () => {
    vaultPending.forEach((p) => p.reject(new Error("vault process exited")));
    vaultPending.clear();
    vaultProc = null;
  });

  return { started: true };
});

ipcMain.handle(
  "vault-query",
  async (_e, req: { id: string; method: string; params: any }) => {
    if (!vaultProc || !vaultProc.stdin) {
      throw new Error("vault process not started");
    }
    return new Promise((resolve, reject) => {
      vaultPending.set(req.id, { resolve, reject });
      vaultProc!.stdin!.write(JSON.stringify(req) + "\n");
      // Bail after 30s so a stuck request doesn't hang forever.
      setTimeout(() => {
        if (vaultPending.has(req.id)) {
          vaultPending.delete(req.id);
          reject(new Error(`vault query timeout: ${req.method}`));
        }
      }, 30000);
    });
  },
);

ipcMain.handle("vault-stop", async () => {
  killVaultProc();
  return { stopped: true };
});

// ── Streaming subprocess (used by Panopto downloader; reusable) ────────
// Spawns a Python script that emits line-delimited JSON on stdout.
// Emits every parsed line as a 'stream-line' event to the renderer.
// Renderer can send input via 'stream-input' (for conflict resolution etc).
let streamProc: ChildProcess | null = null;

function killStreamProc() {
  if (streamProc) {
    streamProc.kill();
    streamProc = null;
  }
}

ipcMain.handle(
  "stream-start",
  async (event, opts: { script: string; args: string[] }) => {
    if (streamProc) killStreamProc();

    const scriptPath = path.join(bundledResources, opts.script);
    streamProc = spawn(bundledPython, [scriptPath, ...opts.args], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    const win = BrowserWindow.fromWebContents(event.sender);
    let buffer = "";

    streamProc.stdout?.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf8");
      let idx: number;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        try {
          const msg = JSON.parse(line);
          win?.webContents.send("stream-line", msg);
        } catch {
          // ignore
        }
      }
    });

    streamProc.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(`[stream] ${chunk.toString("utf8")}`);
    });

    streamProc.on("exit", (code) => {
      win?.webContents.send("stream-exit", { code });
      streamProc = null;
    });

    return { started: true };
  },
);

ipcMain.handle("stream-input", async (_e, data: any) => {
  if (!streamProc || !streamProc.stdin) return { sent: false };
  streamProc.stdin.write(JSON.stringify(data) + "\n");
  return { sent: true };
});

ipcMain.handle("stream-stop", async () => {
  killStreamProc();
  return { stopped: true };
});

app.on("before-quit", killStreamProc);

// Kill vault proc when app quits.
app.on("before-quit", killVaultProc);
