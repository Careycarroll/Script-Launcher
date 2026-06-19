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
	Label      string `json:"label"`
	Default    string `json:"default"`
	FilePicker bool   `json:"filePicker"`
	DirPicker  bool   `json:"dirPicker"`
	MultiFile  bool   `json:"multiFile"`
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
				})
			}
			gd.Scripts = append(gd.Scripts, sd)
		}
		result = append(result, gd)
	}
	return result
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

	// Separate workdir from positional args
	var positional []string
	workDir := ""
	for i, arg := range args {
		if i < len(s.ArgDefs) && s.ArgDefs[i].SetWorkDir {
			workDir = arg
		} else if arg != "" {
			positional = append(positional, arg)
		}
	}

	cmd := exec.Command(s.Path, positional...)
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
