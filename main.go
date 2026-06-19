package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

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

func buildIndex(groups []Group) []itemRef {
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
	stateMenu   viewState = iota // browsing the script list
	statePrompt                  // collecting arguments before run
	stateOutput                  // showing output after a run
)

// ────────────────────────────────────────────────────────────────────────────
// Messages
// ────────────────────────────────────────────────────────────────────────────

type scriptDoneMsg struct {
	output string
	err    error
}

// ────────────────────────────────────────────────────────────────────────────
// Model
// ────────────────────────────────────────────────────────────────────────────

type model struct {
	groups        []Group
	index         []itemRef
	cursor        int
	state         viewState
	output        string
	lastErr       error
	width         int
	height        int
	pendingScript Script
	argInputs     []textinput.Model
	argFocus      int
	vp            viewport.Model
}

func initialModel() model {
	return model{
		groups: registry,
		index:  buildIndex(registry),
	}
}

func makeInputs(defs []Arg) []textinput.Model {
	inputs := make([]textinput.Model, len(defs))
	for i, def := range defs {
		ti := textinput.New()
		ti.Placeholder = def.Default
		ti.CharLimit = 512
		ti.Width = 60
		inputs[i] = ti
	}
	return inputs
}

// ────────────────────────────────────────────────────────────────────────────
// Commands
// ────────────────────────────────────────────────────────────────────────────

func runScript(s Script) tea.Cmd {
	return func() tea.Msg {
		cmd := exec.Command(s.Path, s.Args...)
		cmd.Env = os.Environ()
		out, err := cmd.CombinedOutput()
		return scriptDoneMsg{
			output: string(out),
			err:    err,
		}
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
				if len(script.ArgDefs) > 0 {
					m.pendingScript = script
					m.argInputs = makeInputs(script.ArgDefs)
					m.argFocus = 0
					m.argInputs[0].Focus()
					m.state = statePrompt
					return m, textinput.Blink
				}
				if script.Interactive {
					cmd := exec.Command(script.Path, script.Args...)
					cmd.Env = os.Environ()
					return m, tea.ExecProcess(cmd, func(err error) tea.Msg {
						return scriptDoneMsg{output: "", err: err}
					})
				}
				return m, runScript(script)
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
			case "enter":
				if m.argFocus < len(m.argInputs)-1 {
					m.argInputs[m.argFocus].Blur()
					m.argFocus++
					m.argInputs[m.argFocus].Focus()
					return m, textinput.Blink
				}
				args := make([]string, len(m.argInputs))
				for i, input := range m.argInputs {
					val := input.Value()
					if val == "" && m.pendingScript.ArgDefs[i].Default != "" {
						val = m.pendingScript.ArgDefs[i].Default
					}
					args[i] = val
				}
				m.pendingScript.Args = args
				if m.pendingScript.Interactive {
					cmd := exec.Command(m.pendingScript.Path, args...)
					cmd.Env = os.Environ()
					return m, tea.ExecProcess(cmd, func(err error) tea.Msg {
						return scriptDoneMsg{output: "", err: err}
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

	case scriptDoneMsg:
		m.output = msg.output
		m.lastErr = msg.err
		// Reserve lines for title (2) + help (2) + border (2)
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

	b.WriteString(styleTitle.Render("  🛠  Script Runner") + "\n")

	pos := 0
	for _, group := range m.groups {
		b.WriteString(styleGroupHeader.Render("  ▸ "+group.Name) + "\n")
		for _, script := range group.Scripts {
			isSelected := pos == m.cursor
			if isSelected {
				b.WriteString(styleSelected.Render("▶ "+script.Name) + "\n")
			} else {
				b.WriteString(styleNormal.Render("  "+script.Name) + "\n")
			}
			b.WriteString(styleDesc.Render(script.Description) + "\n")
			pos++
		}
	}

	b.WriteString(styleHelp.Render("  ↑/↓ navigate • enter run • q quit"))
	return b.String()
}

func (m model) viewPrompt() string {
	var b strings.Builder

	b.WriteString(styleTitle.Render("  ⚙  "+m.pendingScript.Name) + "\n\n")

	for i, def := range m.pendingScript.ArgDefs {
		label := def.Label
		if def.Default != "" {
			label += fmt.Sprintf(" (default: %s)", def.Default)
		}
		b.WriteString(styleInputLabel.Render(label) + "\n")
		if i == m.argFocus {
			b.WriteString(styleInputActive.Render(m.argInputs[i].View()) + "\n\n")
		} else {
			b.WriteString(styleInputInactive.Render(m.argInputs[i].View()) + "\n\n")
		}
	}

	b.WriteString(styleHelp.Render("  tab/↓ next • shift+tab/↑ prev • enter confirm • esc back"))
	return b.String()
}

func (m model) viewOutput() string {
	var b strings.Builder

	title := "  ✓  Output"
	if m.lastErr != nil {
		title = styleError.Render("  ✗  Error")
	}
	b.WriteString(styleTitle.Render(title) + "\n")

	b.WriteString(styleOutput.Render(m.vp.View()) + "\n")

	scrollPct := 0
	if m.vp.TotalLineCount() > 0 {
		scrollPct = int(m.vp.ScrollPercent() * 100)
	}
	b.WriteString(styleHelp.Render(fmt.Sprintf("  ↑/↓ scroll • %d%% • esc/b back • q quit", scrollPct)))
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
