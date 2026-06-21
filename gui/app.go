package main

import (
	"context"
	"os"
	"os/exec"
	"strings"

	"scripttui/registry"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// ── Serialisable types for the frontend ──────────────────────────────────────

type ArgData struct {
	Label      string   `json:"label"`
	Default    string   `json:"default"`
	FilePicker bool     `json:"filePicker"`
	DirPicker  bool     `json:"dirPicker"`
	MultiFile  bool     `json:"multiFile"`
	Options    []string `json:"options"`
}

type ScriptData struct {
	Name        string    `json:"name"`
	Description string    `json:"description"`
	Help        string    `json:"help"`
	Interactive bool      `json:"interactive"`
	ArgDefs     []ArgData `json:"argDefs"`
}

type GroupData struct {
	Name    string       `json:"name"`
	Scripts []ScriptData `json:"scripts"`
}

type RunResult struct {
	Output string `json:"output"`
	Error  string `json:"error"`
}

// ── App ───────────────────────────────────────────────────────────────────────

type App struct {
	ctx context.Context
}

func NewApp() *App {
	return &App{}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

// ── Exposed to frontend ───────────────────────────────────────────────────────

// GetGroups returns all script groups and their scripts.
func (a *App) GetGroups() []GroupData {
	var result []GroupData
	for _, g := range registry.Groups {
		gd := GroupData{Name: g.Name}
		for _, s := range g.Scripts {
			sd := ScriptData{
				Name:        s.Name,
				Description: s.Description,
				Help:        s.Help,
				Interactive: s.Interactive,
			}
			for _, arg := range s.ArgDefs {
				sd.ArgDefs = append(sd.ArgDefs, ArgData{
					Label:      arg.Label,
					Default:    arg.Default,
					FilePicker: arg.FilePicker,
					DirPicker:  arg.DirPicker,
					MultiFile:  arg.MultiFile,
					Options:    arg.Options,
				})
			}
			gd.Scripts = append(gd.Scripts, sd)
		}
		result = append(result, gd)
	}
	return result
}

// isDir returns true if the given path is a directory.
func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// RunScript executes a script by group/script index with the provided args.
func (a *App) RunScript(groupIdx int, scriptIdx int, args []string) RunResult {
	if groupIdx >= len(registry.Groups) {
		return RunResult{Error: "invalid group index"}
	}
	g := registry.Groups[groupIdx]
	if scriptIdx >= len(g.Scripts) {
		return RunResult{Error: "invalid script index"}
	}
	s := registry.Groups[groupIdx].Scripts[scriptIdx]

	// Interactive scripts open in a new Terminal window via .command file
	if s.Interactive {
		cmdFile := "/tmp/run_script.command"
		content := "#!/bin/bash\n" +
			"export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:/Users/careycarroll/bin\n" +
			s.Path + "\n"
		if err := os.WriteFile(cmdFile, []byte(content), 0755); err != nil {
			return RunResult{Error: "failed to write command file: " + err.Error()}
		}
		cmd := exec.Command("open", cmdFile)
		if err := cmd.Start(); err != nil {
			return RunResult{Error: err.Error()}
		}
		go cmd.Wait()
		return RunResult{Output: "Launched in Terminal"}
	}

	// Build flags and positional args
	var flags []string
	var positional []string
	workDir := ""
	for i, arg := range args {
		if arg == "" {
			continue
		}
		if i < len(s.ArgDefs) && s.ArgDefs[i].SetWorkDir && isDir(arg) {
			workDir = arg
		} else if i < len(s.ArgDefs) && s.ArgDefs[i].Flag != "" {
			flags = append(flags, s.ArgDefs[i].Flag, arg)
		} else {
			positional = append(positional, arg)
		}
	}
	allArgs := append(flags, positional...)

	cmd := exec.Command(s.Path, allArgs...)
	cmd.Env = os.Environ()
	if workDir != "" {
		cmd.Dir = workDir
	}

	out, err := cmd.CombinedOutput()
	result := RunResult{Output: string(out)}
	if err != nil {
		result.Error = err.Error()
	}
	return result
}

// PickFile opens a native macOS file picker and returns the selected path.
func (a *App) PickFile() string {
	path, err := runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "Select File",
	})
	if err != nil {
		return ""
	}
	return path
}

// PickFolder opens a native macOS folder picker and returns the selected path.
func (a *App) PickFolder() string {
	path, err := runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "Select Folder",
	})
	if err != nil {
		return ""
	}
	return strings.TrimSpace(path)
}
