package main

// Arg defines a single prompted argument for a script.
type Arg struct {
	Label   string
	Default string
}

// Script defines a single runnable tool.
type Script struct {
	Name        string
	Description string
	Path        string // absolute path to the binary/script
	Args        []string
	ArgDefs     []Arg
	Interactive bool
}

// Group is a named collection of scripts.
type Group struct {
	Name    string
	Scripts []Script
}

// registry is the master list of all tool groups.
// Add new scripts here as you create them.
var registry = []Group{
	{
		Name: "Vault",
		Scripts: []Script{
			{
				Name:        "Manage Vault",
				Description: "Full vault management — create, edit, and organise vault entries",
				Path:        "/Users/careycarroll/bin/manage_vault",
				Interactive: true,
			},
			{
				Name:        "Add Vault Link",
				Description: "Add a new link / reference into the vault",
				Path:        "/Users/careycarroll/bin/add_vault_link",
				Interactive: true,
				ArgDefs: []Arg{
					{Label: "File path"},
					{Label: "Wikilink (e.g. [[Note Name]])"},
					{Label: "Reason"},
					{Label: "Subsection", Default: "Related prior session notes"},
				},
			},
			{
				Name:        "Vault Health",
				Description: "Check vault integrity and surface broken or orphaned entries",
				Path:        "/Users/careycarroll/bin/vault_health",
			},
			{
				Name:        "Cleanup Vault Tools",
				Description: "Remove temporary files and stale artefacts left by vault tools",
				Path:        "/Users/careycarroll/bin/cleanup_vault_tools.sh",
				Interactive: true,
			},
		},
	},
	{
		Name: "Documents",
		Scripts: []Script{
			{
				Name:        "PDF → Text",
				Description: "Extract plain text from a PDF file",
				Path:        "/Users/careycarroll/bin/pdf2txt",
				ArgDefs: []Arg{
					{Label: "PDF file path"},
				},
			},
			{
				Name:        "PPTX → PDF",
				Description: "Convert a PowerPoint presentation to PDF",
				Path:        "/Users/careycarroll/bin/pptx2pdf",
				ArgDefs: []Arg{
					{Label: "PPTX file path"},
				},
			},
		},
	},
}
