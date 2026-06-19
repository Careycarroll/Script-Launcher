package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	"scripttui/registry"

	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ────────────────────────────────────────────────────────────────────────────
// Styles
// ────────────────────────────────────────────────────────────────────────────

var (
	styleTitle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("#FAFAFA")).
			Background(lipgloss.Color("#5C7CFA")).
			Padding(0, 2).
			MarginBottom(1)

	styleGroupHeader = lipgloss.NewStyle().
				Bold(true).
				Foreground(lipgloss.Color("#5C7CFA")).
				MarginTop(1)

	styleSelected = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FAFAFA")).
			Background(lipgloss.Color("#5C7CFA")).
			Padding(0, 2)

	styleNormal = lipgloss.NewStyle().
			Padding(0, 2)

	styleDesc = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#888888")).
			Padding(0, 4)

	styleHelp = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#555555")).
			MarginTop(1)

	styleOutput = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#5C7CFA")).
			Padding(1, 2).
			MarginTop(1)

	styleError = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FF6B6B")).
			Bold(true)

	styleInputLabel = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FAFAFA")).
			Bold(true).
			Padding(0, 2)

	styleInputActive = lipgloss.NewStyle().
				Border(lipgloss.RoundedBorder()).
				BorderForeground(lipgloss.Color("#5C7CFA")).
				Padding(0, 1).
				MarginLeft(2)

	styleInputInactive = lipgloss.NewStyle().
				Border(lipgloss.RoundedBorder()).
				BorderForeground(lipgloss.Color("#444444")).
				Padding(0, 1).
				MarginLeft(2)
)

// ────────────────────────────────────────────────────────────────────────────
// Flat index: map linear cursor position → (group, script)
// ────────────────────────────────────────────────────────────────────────────

type itemRef struct {
	groupIdx  int
	scriptIdx int
}

func buildIndex(groups []registry.Group) []itemRef {
	var idx []itemRef
	for g, group := range groups {
		for s := range group.Scripts {
			idx = append(idx, itemRef{g, s})
		}
	}
	return idx
}

// ────────────────────────────────────────────────────────────────────────────
// View states
// ────────────────────────────────────────────────────────────────────────────

type viewState int

const (
	stateMenu    viewState = iota
	stateConfirm
	stateQueue
	statePrompt
	stateOutput
)

// ────────────────────────────────────────────────────────────────────────────
// Messages
// ────────────────────────────────────────────────────────────────────────────

type scriptDoneMsg struct {
	output      string
	err         error
	interactive bool
}

type filePickerMsg struct {
	path string
	err  error
}

// ────────────────────────────────────────────────────────────────────────────
// Model
// ────────────────────────────────────────────────────────────────────────────

type model struct {
	groups        []registry.Group
	index         []itemRef
	cursor        int
	state         viewState
	output        string
	lastErr       error
	width         int
	height        int
	pendingScript registry.Script
	argInputs     []textinput.Model
	argFocus      int
	vp            viewport.Model
	fileQueue     []string
}

func initialModel() model {
	return model{
		groups: registry.Groups,
		index:  buildIndex(registry.Groups),
	}
}

func makeInputs(defs []registry.Arg, width int) []textinput.Model {
	inputs := make([]textinput.Model, len(defs))
	for i, def := range defs {
		ti := textinput.New()
		ti.Placeholder = def.Default
		ti.CharLimit = 512
		if width > 0 {
			ti.Width = width - 12
		} else {
			ti.Width = 60
		}
		inputs[i] = ti
	}
	return inputs
}

// ────────────────────────────────────────────────────────────────────────────
// Commands
// ────────────────────────────────────────────────────────────────────────────

func runFilePicker(dirMode bool) tea.Cmd {
	return func() tea.Msg {
		script := "POSIX path of (choose file)"
		if dirMode {
			script = "POSIX path of (choose folder)"
		}
		out, err := exec.Command("osascript", "-e", script).Output()
		if err != nil {
			return filePickerMsg{err: err}
		}
		return filePickerMsg{path: strings.TrimSpace(string(out))}
	}
}

func runScriptWithFiles(s registry.Script, files []string) tea.Cmd {
	batchMode := false
	for _, def := range s.ArgDefs {
		if def.BatchArgs {
			batchMode = true
			break
		}
	}
	return func() tea.Msg {
		if batchMode {
			cmd := exec.Command(s.Path, files...)
			cmd.Env = os.Environ()
			out, err := cmd.CombinedOutput()
			return scriptDoneMsg{output: string(out), err: err}
		}
		// Run once per file, concatenate output
		var combined strings.Builder
		var lastErr error
		for _, f := range files {
			cmd := exec.Command(s.Path, f)
			cmd.Env = os.Environ()
			out, err := cmd.CombinedOutput()
			if len(files) > 1 {
				combined.WriteString(fmt.Sprintf("── %s ──\n", f))
			}
			combined.WriteString(string(out))
			combined.WriteString("\n")
			if err != nil {
				lastErr = err
			}
		}
		return scriptDoneMsg{output: combined.String(), err: lastErr}
	}
}

func runScript(s registry.Script) tea.Cmd {
	return func() tea.Msg {
		var positional []string
		workDir := ""
		for i, arg := range s.Args {
			if i < len(s.ArgDefs) && s.ArgDefs[i].SetWorkDir {
				workDir = arg
			} else {
				positional = append(positional, arg)
			}
		}
		cmd := exec.Command(s.Path, positional...)
		cmd.Env = os.Environ()
		if workDir != "" {
			cmd.Dir = workDir
		}
		out, err := cmd.CombinedOutput()
		return scriptDoneMsg{output: string(out), err: err}
	}
}

// ────────────────────────────────────────────────────────────────────────────
// Init
// ────────────────────────────────────────────────────────────────────────────

func (m model) Init() tea.Cmd {
	return nil
}

// ────────────────────────────────────────────────────────────────────────────
// Update
// ────────────────────────────────────────────────────────────────────────────

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height

	case tea.KeyMsg:
		switch m.state {

		case stateMenu:
			switch msg.String() {
			case "q", "ctrl+c":
				return m, tea.Quit
			case "up", "k":
				if m.cursor > 0 {
					m.cursor--
				}
			case "down", "j":
				if m.cursor < len(m.index)-1 {
					m.cursor++
				}
			case "enter", " ":
				ref := m.index[m.cursor]
				script := m.groups[ref.groupIdx].Scripts[ref.scriptIdx]

				hasMultiFile := false
				for _, def := range script.ArgDefs {
					if def.MultiFile {
						hasMultiFile = true
						break
					}
				}
				if hasMultiFile {
					m.pendingScript = script
					m.fileQueue = nil
					m.state = stateQueue
					return m, nil
				}

				if len(script.ArgDefs) > 0 {
					m.pendingScript = script
					m.argInputs = makeInputs(script.ArgDefs, m.width)
					m.argFocus = 0
					m.argInputs[0].Focus()
					m.state = statePrompt
					return m, textinput.Blink
				}
				m.pendingScript = script
				m.state = stateConfirm
				return m, nil
			}

		case stateConfirm:
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "b":
				m.state = stateMenu
				return m, nil
			case "enter":
				if m.pendingScript.Interactive {
					cmd := exec.Command(m.pendingScript.Path, m.pendingScript.Args...)
					cmd.Env = os.Environ()
					return m, tea.ExecProcess(cmd, func(err error) tea.Msg {
						return scriptDoneMsg{output: "", err: err, interactive: true}
					})
				}
				return m, runScript(m.pendingScript)
			}

		case stateQueue:
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc", "b":
				m.state = stateMenu
				m.fileQueue = nil
				return m, nil
			case "f":
				return m, runFilePicker(false)
			case "d":
				hasDirPicker := false
				for _, def := range m.pendingScript.ArgDefs {
					if def.DirPicker {
						hasDirPicker = true
						break
					}
				}
				if hasDirPicker {
					return m, runFilePicker(true)
				}
			case "backspace":
				if len(m.fileQueue) > 0 {
					m.fileQueue = m.fileQueue[:len(m.fileQueue)-1]
				}
				return m, nil
			case "enter":
				if len(m.fileQueue) == 0 {
					return m, nil
				}
				return m, runScriptWithFiles(m.pendingScript, m.fileQueue)
			}

		case statePrompt:
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc":
				m.state = stateMenu
				m.argInputs = nil
				return m, nil
			case "tab", "down":
				m.argInputs[m.argFocus].Blur()
				m.argFocus = (m.argFocus + 1) % len(m.argInputs)
				m.argInputs[m.argFocus].Focus()
				return m, textinput.Blink
			case "shift+tab", "up":
				m.argInputs[m.argFocus].Blur()
				m.argFocus = (m.argFocus - 1 + len(m.argInputs)) % len(m.argInputs)
				m.argInputs[m.argFocus].Focus()
				return m, textinput.Blink
			case "f":
				if m.pendingScript.ArgDefs[m.argFocus].FilePicker || m.pendingScript.ArgDefs[m.argFocus].DirPicker {
					return m, runFilePicker(m.pendingScript.ArgDefs[m.argFocus].DirPicker)
				}
				var cmd tea.Cmd
				m.argInputs[m.argFocus], cmd = m.argInputs[m.argFocus].Update(msg)
				return m, cmd
			case "enter":
				if m.argFocus < len(m.argInputs)-1 {
					m.argInputs[m.argFocus].Blur()
					m.argFocus++
					m.argInputs[m.argFocus].Focus()
					return m, textinput.Blink
				}
				var args []string
				for i, input := range m.argInputs {
					val := input.Value()
					if val == "" && m.pendingScript.ArgDefs[i].Default != "" {
						val = m.pendingScript.ArgDefs[i].Default
					}
					if val != "" {
						args = append(args, val)
					}
				}
				m.pendingScript.Args = args
				if m.pendingScript.Interactive {
					cmd := exec.Command(m.pendingScript.Path, args...)
					cmd.Env = os.Environ()
					return m, tea.ExecProcess(cmd, func(err error) tea.Msg {
						return scriptDoneMsg{output: "", err: err, interactive: true}
					})
				}
				return m, runScript(m.pendingScript)
			default:
				var cmd tea.Cmd
				m.argInputs[m.argFocus], cmd = m.argInputs[m.argFocus].Update(msg)
				return m, cmd
			}

		case stateOutput:
			switch msg.String() {
			case "q", "ctrl+c":
				return m, tea.Quit
			case "esc", "b":
				m.state = stateMenu
				m.output = ""
				m.lastErr = nil
			default:
				var cmd tea.Cmd
				m.vp, cmd = m.vp.Update(msg)
				return m, cmd
			}
		}

	case filePickerMsg:
		if msg.err == nil && msg.path != "" {
			if m.state == stateQueue {
				m.fileQueue = append(m.fileQueue, msg.path)
			} else {
				m.argInputs[m.argFocus].SetValue(msg.path)
			}
		}
		return m, nil

	case scriptDoneMsg:
		if msg.interactive {
			m.state = stateMenu
			return m, nil
		}
		m.output = msg.output
		m.lastErr = msg.err
		vpHeight := m.height - 6
		if vpHeight < 5 {
			vpHeight = 5
		}
		vpWidth := m.width - 6
		if vpWidth < 20 {
			vpWidth = 20
		}
		m.vp = viewport.New(vpWidth, vpHeight)
		if msg.err != nil {
			m.vp.SetContent(fmt.Sprintf("Error: %v\n\n%s", msg.err, msg.output))
		} else if msg.output == "" {
			m.vp.SetContent("(no output)")
		} else {
			m.vp.SetContent(msg.output)
		}
		m.state = stateOutput
	}

	return m, nil
}

// ────────────────────────────────────────────────────────────────────────────
// View
// ────────────────────────────────────────────────────────────────────────────

func (m model) View() string {
	switch m.state {
	case stateConfirm:
		return m.viewConfirm()
	case stateQueue:
		return m.viewQueue()
	case statePrompt:
		return m.viewPrompt()
	case stateOutput:
		return m.viewOutput()
	default:
		return m.viewMenu()
	}
}

func (m model) viewMenu() string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("⚡ Script Launcher") + "\n")

	pos := 0
	for _, group := range m.groups {
		b.WriteString(styleGroupHeader.Render("▸ "+group.Name) + "\n")
		for _, script := range group.Scripts {
			isSelected := pos == m.cursor
			if isSelected {
				b.WriteString(styleSelected.Render("▶ "+script.Name) + "\n")
			} else {
				b.WriteString(styleNormal.Render("  "+script.Name) + "\n")
			}
			b.WriteString(styleDesc.Width(m.width - 4).Render(script.Description) + "\n")
			pos++
		}
	}

	b.WriteString(styleHelp.Width(m.width - 4).Render("↑/↓ navigate • enter run • q quit"))
	return b.String()
}

func (m model) viewConfirm() string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("⚡ "+m.pendingScript.Name) + "\n\n")
	b.WriteString(styleDesc.Width(m.width - 4).Render(m.pendingScript.Description) + "\n\n")
	if m.pendingScript.Help != "" {
		b.WriteString(styleDesc.Width(m.width - 4).Render(m.pendingScript.Help) + "\n\n")
	}
	b.WriteString(styleHelp.Width(m.width - 4).Render("enter run • esc back"))
	return b.String()
}

func (m model) viewQueue() string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("⚡ "+m.pendingScript.Name) + "\n\n")
	if m.pendingScript.Help != "" {
		b.WriteString(styleDesc.Width(m.width - 4).Render(m.pendingScript.Help) + "\n\n")
	}

	if len(m.fileQueue) == 0 {
		b.WriteString(styleDesc.Render("No files queued — press f to add") + "\n\n")
	} else {
		b.WriteString(styleNormal.Render("Files queued:") + "\n")
		for i, f := range m.fileQueue {
			b.WriteString(styleDesc.Width(m.width - 4).Render(fmt.Sprintf("%d. %s", i+1, f)) + "\n")
		}
		b.WriteString("\n")
	}

	b.WriteString(func() string {
		hint := "f add file"
		hasDirPicker := false
		for _, def := range m.pendingScript.ArgDefs {
			if def.DirPicker {
				hasDirPicker = true
				break
			}
		}
		if hasDirPicker {
			hint += " • d add folder"
		}
		hint += " • backspace remove last • enter run • esc back"
		return styleHelp.Width(m.width - 4).Render(hint)
	}())
	return b.String()
}

func (m model) viewPrompt() string {
	var b strings.Builder
	b.WriteString(styleTitle.Render("⚡ "+m.pendingScript.Name) + "\n\n")
	if m.pendingScript.Help != "" {
		b.WriteString(styleDesc.Width(m.width - 4).Render(m.pendingScript.Help) + "\n\n")
	}

	for i, def := range m.pendingScript.ArgDefs {
		b.WriteString(styleInputLabel.Width(m.width - 4).Render(def.Label) + "\n")
		if i == m.argFocus {
			b.WriteString(styleInputActive.Width(m.width - 6).Render(m.argInputs[i].View()) + "\n\n")
		} else {
			b.WriteString(styleInputInactive.Width(m.width - 6).Render(m.argInputs[i].View()) + "\n\n")
		}
	}

	if m.pendingScript.ArgDefs[m.argFocus].FilePicker || m.pendingScript.ArgDefs[m.argFocus].DirPicker {
		b.WriteString(styleHelp.Width(m.width - 4).Render("tab/↓ next field • shift+tab/↑ prev • enter run • esc back • f pick file"))
	} else {
		b.WriteString(styleHelp.Width(m.width - 4).Render("tab/↓ next field • shift+tab/↑ prev • enter run • esc back"))
	}
	return b.String()
}

func (m model) viewOutput() string {
	var b strings.Builder
	title := "✓ Output"
	if m.lastErr != nil {
		title = styleError.Render("✗ Error")
	}
	b.WriteString(styleTitle.Render(title) + "\n")
	b.WriteString(styleOutput.Render(m.vp.View()) + "\n")

	scrollPct := 0
	if m.vp.TotalLineCount() > 0 {
		scrollPct = int(m.vp.ScrollPercent() * 100)
	}
	b.WriteString(styleHelp.Width(m.width - 4).Render(fmt.Sprintf("↑/↓ scroll • %d%% • esc/b → back • q quit", scrollPct)))
	return b.String()
}

// ────────────────────────────────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────────────────────────────────

func main() {
	p := tea.NewProgram(initialModel(), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}
