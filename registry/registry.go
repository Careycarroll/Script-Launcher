package registry

// Arg defines a single prompted argument for a script.
type Arg struct {
	Label      string
	Default    string
	FilePicker bool
	DirPicker  bool
	SetWorkDir bool
	MultiFile  bool
	BatchArgs  bool
	Options    []string
	Flag       string
}

// Script defines a single runnable tool.
type Script struct {
	Name        string
	Description string
	Path        string
	Args        []string
	ArgDefs     []Arg
	Interactive bool
	Help        string
}

// Group is a named collection of scripts.
type Group struct {
	Name    string
	Scripts []Script
}

// Groups is the master list of all tool groups.
// Add new scripts here as you create them.
var Groups = []Group{
	{
		Name: "Vault",
		Scripts: []Script{
			{
				Name:        "Manage Vault",
				Description: "Full vault management — create, edit, and organise vault entries",
				Path:        "/Users/careycarroll/bin/manage_vault",
				Help:        "CAWC Vault Session Manager. Handles course registration and pre-session setup. Launches a full interactive TUI — use its own menus to navigate. Returns here when you exit.",
				Interactive: true,
			},
			{
				Name:        "Add Vault Link",
				Description: "Add a new link / reference into the vault",
				Path:        "/Users/careycarroll/bin/add_vault_link",
				Help:        "Inserts a wikilink into the Supporting Content section of an Obsidian note. Creates the section automatically if it does not exist. Appends after the last entry in the target subsection. Expires September 30, 2027.",
				ArgDefs: []Arg{
					{Label: "File path", FilePicker: true},
					{Label: "Wikilink (e.g. [[Note Name]])"},
					{Label: "Reason"},
					{Label: "Subsection", Default: "Related prior session notes"},
				},
			},
			{
				Name:        "Vault Health",
				Description: "Check vault integrity and surface broken or orphaned entries",
				Path:        "/Users/careycarroll/bin/vault_health",
				Help:        "Scans the CAWC Obsidian vault for broken wikilinks and orphaned notes. Ignores index files (prefixed _), image links, and stub notes. Outputs a report to the terminal and writes a markdown report to Obsidian at Help/Vault Health Report.md.",
			},
			{
				Name:        "Cleanup Vault Tools",
				Description: "Remove temporary files and stale artefacts left by vault tools",
				Path:        "/Users/careycarroll/bin/cleanup_vault_tools.sh",
				Help:        "Time-gated cleanup — only takes action on or after December 2027. When triggered, removes: add_vault_link, the cleanup LaunchAgent plist, and this script itself. Before that date it runs and exits silently with no changes made.",
				Interactive: true,
			},
		},
	},
	{
		Name: "Documents",
		Scripts: []Script{
			{
				Name:        "PDF → Text",
				Description: "Extract plain text from one or more PDF files",
				Path:        "/Users/careycarroll/bin/pdf2txt",
				Help:        "Converts PDFs to plain text. Queue one or more files — each is converted individually. Output defaults to a .txt file in the same directory as the input.",
				ArgDefs: []Arg{
					{Label: "PDF files", FilePicker: true, MultiFile: true},
				},
			},
			{
				Name:        "PPTX → PDF",
				Description: "Convert PowerPoint presentations to PDF",
				Path:        "/Users/careycarroll/bin/pptx2pdf",
				Help:        "Converts .pptx files to PDF using Microsoft PowerPoint. Queue individual files or add from Finder. All queued files are converted in one pass. Compresses at 150 DPI (ebook) by default. Requires PowerPoint and Ghostscript (brew install ghostscript).",
				ArgDefs: []Arg{
					{Label: "PPTX files", FilePicker: true, DirPicker: true, MultiFile: true, BatchArgs: true, SetWorkDir: true},
					{Label: "Compression", Default: "ebook", Flag: "-c", Options: []string{"screen", "ebook", "printer", "prepress", "default", "none"}},
				},
			},
		},
	},
}
