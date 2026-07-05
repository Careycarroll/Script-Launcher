import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  tabCount,
  OverviewTab,
  OrphansTab,
  BrokenLinksTab,
  TagsTab,
  DuplicatesTab,
  ComponentsTab,
} from "../src/tiles/VaultWorkbench.jsx";

// Fixture: a small but realistic vault index shape based on vault_index.py output.
const fixtureIndex = {
  note_count: 6,
  edges: [
    { source: "A", target: "B", type: "wikilink" },
    { source: "A", target: "C", type: "wikilink" },
    { source: "B", target: "C", type: "wikilink" },
    { source: "D", target: "MissingNote", type: "wikilink" },
  ],
  orphans: ["Loose1", "Loose2", "OrphanNote"],
  broken_links: [
    { source: "D", target: "MissingNote", type: "wikilink" },
    { source: "E", target: "AlsoMissing", type: "wikilink" },
  ],
  tag_counts: {
    project: 5,
    idea: 3,
    todo: 1,
  },
  duplicate_titles: [
    {
      title: "Meeting Notes",
      paths: ["work/meeting.md", "personal/meeting.md"],
    },
  ],
  components: [10, 3, 3, 1, 1, 1],
  hubs: Array.from({ length: 20 }, (_, i) => ({
    title: `Hub${i + 1}`,
    in_degree: 20 - i,
  })),
  notes: [],
};

describe("tabCount", () => {
  it("returns correct count for each known tab", () => {
    expect(tabCount("Overview", fixtureIndex)).toBe(6);
    expect(tabCount("Graph", fixtureIndex)).toBe(6);
    expect(tabCount("Orphans", fixtureIndex)).toBe(3);
    expect(tabCount("Broken Links", fixtureIndex)).toBe(2);
    expect(tabCount("Tags", fixtureIndex)).toBe(3);
    expect(tabCount("Duplicates", fixtureIndex)).toBe(1);
    expect(tabCount("Components", fixtureIndex)).toBe(6);
  });

  it("returns empty string for unknown tab", () => {
    expect(tabCount("Nonsense", fixtureIndex)).toBe("");
  });
});

describe("OverviewTab", () => {
  it("renders all five metric values", () => {
    const { container } = render(<OverviewTab index={fixtureIndex} />);
    // Metric values render inside .vault-metric-value spans (one per metric).
    // Query those specifically so we don't collide with hub in_degree spans.
    const metricValues = container.querySelectorAll(".vault-metric-value");
    expect(metricValues).toHaveLength(5);
    expect(metricValues[0]).toHaveTextContent("6"); // notes
    expect(metricValues[1]).toHaveTextContent("4"); // edges
    expect(metricValues[2]).toHaveTextContent("2"); // broken links
    expect(metricValues[3]).toHaveTextContent("3"); // orphans
    expect(metricValues[4]).toHaveTextContent("6"); // components
  });

  it("caps top hubs display at 15 rows", () => {
    render(<OverviewTab index={fixtureIndex} />);
    // fixture has 20 hubs; component slices to first 15
    expect(screen.getByText("Hub1")).toBeInTheDocument();
    expect(screen.getByText("Hub15")).toBeInTheDocument();
    expect(screen.queryByText("Hub16")).not.toBeInTheDocument();
    expect(screen.queryByText("Hub20")).not.toBeInTheDocument();
  });
});

describe("OrphansTab", () => {
  it("renders all orphans and the count", () => {
    render(<OrphansTab index={fixtureIndex} />);
    expect(screen.getByText("Loose1")).toBeInTheDocument();
    expect(screen.getByText("Loose2")).toBeInTheDocument();
    expect(screen.getByText("OrphanNote")).toBeInTheDocument();
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
  });

  it("filters case-insensitively", () => {
    render(<OrphansTab index={fixtureIndex} />);
    const filter = screen.getByPlaceholderText(/filter orphans/i);
    fireEvent.change(filter, { target: { value: "LOOSE" } });
    expect(screen.getByText("Loose1")).toBeInTheDocument();
    expect(screen.getByText("Loose2")).toBeInTheDocument();
    expect(screen.queryByText("OrphanNote")).not.toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("shows empty state when filter matches nothing", () => {
    render(<OrphansTab index={fixtureIndex} />);
    fireEvent.change(screen.getByPlaceholderText(/filter orphans/i), {
      target: { value: "zzzzz" },
    });
    expect(
      screen.getByText(/No orphans match your filter/i),
    ).toBeInTheDocument();
  });
});

describe("BrokenLinksTab", () => {
  it("renders source, target, and type for each broken link", () => {
    render(<BrokenLinksTab index={fixtureIndex} />);
    expect(screen.getByText("D")).toBeInTheDocument();
    expect(screen.getByText("MissingNote")).toBeInTheDocument();
    expect(screen.getByText("E")).toBeInTheDocument();
    expect(screen.getByText("AlsoMissing")).toBeInTheDocument();
    // 'wikilink' text appears twice — use getAllByText.
    expect(screen.getAllByText("wikilink")).toHaveLength(2);
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
  });

  it("filter matches source OR target substring", () => {
    render(<BrokenLinksTab index={fixtureIndex} />);
    const filter = screen.getByPlaceholderText(/filter broken links/i);
    // Filter by target substring
    fireEvent.change(filter, { target: { value: "AlsoMissing" } });
    expect(screen.getByText("E")).toBeInTheDocument();
    expect(screen.queryByText("MissingNote")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });

  it("shows empty state when filter matches nothing", () => {
    render(<BrokenLinksTab index={fixtureIndex} />);
    fireEvent.change(screen.getByPlaceholderText(/filter broken links/i), {
      target: { value: "zzzzz" },
    });
    expect(
      screen.getByText(/No broken links match your filter/i),
    ).toBeInTheDocument();
  });
});

describe("TagsTab", () => {
  it("renders each tag with its count, bar width proportional to max", () => {
    const { container } = render(<TagsTab index={fixtureIndex} />);
    expect(screen.getByText("project")).toBeInTheDocument();
    expect(screen.getByText("idea")).toBeInTheDocument();
    expect(screen.getByText("todo")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    // Max is 5 → project bar 100%, idea 60%, todo 20%
    const bars = container.querySelectorAll(".vault-tag-bar");
    expect(bars[0]).toHaveStyle({ width: "100%" });
    expect(bars[1]).toHaveStyle({ width: "60%" });
    expect(bars[2]).toHaveStyle({ width: "20%" });
  });

  it("filters case-insensitively by tag name", () => {
    render(<TagsTab index={fixtureIndex} />);
    fireEvent.change(screen.getByPlaceholderText(/filter tags/i), {
      target: { value: "PROJ" },
    });
    expect(screen.getByText("project")).toBeInTheDocument();
    expect(screen.queryByText("idea")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("shows empty state when filter matches nothing", () => {
    render(<TagsTab index={fixtureIndex} />);
    fireEvent.change(screen.getByPlaceholderText(/filter tags/i), {
      target: { value: "zzzzz" },
    });
    expect(screen.getByText(/No tags match your filter/i)).toBeInTheDocument();
  });
});

describe("DuplicatesTab", () => {
  it("renders each duplicate title with its paths", () => {
    render(<DuplicatesTab index={fixtureIndex} />);
    expect(screen.getByText("Meeting Notes")).toBeInTheDocument();
    expect(screen.getByText("work/meeting.md")).toBeInTheDocument();
    expect(screen.getByText("personal/meeting.md")).toBeInTheDocument();
  });

  it("shows empty state when no duplicates", () => {
    render(<DuplicatesTab index={{ ...fixtureIndex, duplicate_titles: [] }} />);
    expect(screen.getByText(/No duplicate titles/i)).toBeInTheDocument();
  });
});

describe("ComponentsTab", () => {
  it("groups components by size, sorted descending by size", () => {
    const { container } = render(<ComponentsTab index={fixtureIndex} />);
    // fixture components: [10, 3, 3, 1, 1, 1]
    // groups: 10→1, 3→2, 1→3
    // sorted desc: size 10 first, then 3, then 1
    const rows = container.querySelectorAll(".vault-list-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("1 component of size 10");
    expect(rows[1]).toHaveTextContent("2 components of size 3");
    expect(rows[2]).toHaveTextContent("3 components of size 1");
  });

  it("uses singular 'component' when count is 1", () => {
    render(<ComponentsTab index={fixtureIndex} />);
    // size 10 has count 1 → 'component' not 'components'
    const el = screen.getByText(/1 component of size 10/);
    expect(el.textContent).toContain("1 component of size 10");
    expect(el.textContent).not.toContain("components of size 10");
  });

  it("appends '(isolated notes)' only for size 1", () => {
    render(<ComponentsTab index={fixtureIndex} />);
    expect(
      screen.getByText(/of size 1 \(isolated notes\)/),
    ).toBeInTheDocument();
    // size 3 should NOT have the isolated suffix
    const size3 = screen.getByText(/of size 3$/);
    expect(size3.textContent).not.toContain("isolated");
  });
});
