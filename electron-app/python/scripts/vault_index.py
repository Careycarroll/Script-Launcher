#!/usr/bin/env python3
"""
vault_index.py — Standalone Obsidian vault indexer.

Walks a vault directory, parses every .md file for wikilinks, embeds, and
YAML frontmatter tags, and emits a single JSON document to stdout (or --out).

Handles Obsidian quirks:
  - YAML frontmatter (list-form and inline-list-form tags)
  - Wikilinks: [[X]], [[X|alias]], [[X#section]]
  - Path-style wikilinks: [[folder/subfolder/Note]] resolve by basename
  - Section-only links [[#section]] filtered out (in-page navigation)
  - Embeds ![[X]] distinguished from wikilinks; .md targets = note embeds,
    others = asset embeds
  - Directory-based exclusion (see DEFAULT_EXCLUDE_DIRS)
  - iCloud offloading: `brctl download <vault>` upfront by default

Emits:
  - notes: list of {rel_path, title, tags, wikilinks, embeds, asset_embeds}
  - edges: derived (source, target, type) tuples for graph rendering
  - orphans: notes with no incoming edges
  - broken_links: (source, target) where target has no matching note
  - hubs: top-20 by in-degree
  - components: connected-component sizes (undirected)
  - tag_counts: frequency map
  - duplicate_titles: notes sharing a stem across directories

See ADR-0005 for design rationale.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

import yaml


# ── Configuration ──────────────────────────────────────────────────────────
# Directories excluded by default. Match on directory NAME, not path.
# Match is exact and case-sensitive. Users can override with --exclude-dir.
DEFAULT_EXCLUDE_DIRS = {'__Templates', '_Assets', '.obsidian', '.trash'}


# ── Regexes ────────────────────────────────────────────────────────────────
# Wikilink:  [[target]] | [[target|alias]] | [[target#section]] | [[target#section|alias]]
# Not embed (no leading !). Captures the target only.
WIKILINK_RE = re.compile(r'(?<!\!)\[\[([^\[\]|#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]')

# Embed: ![[target]] with same variants.
EMBED_RE = re.compile(r'\!\[\[([^\[\]|#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]')

FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


# ── Parsers ────────────────────────────────────────────────────────────────
def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter if present. Returns {} on absence or parse error."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def normalize_tags(fm: dict) -> list[str]:
    """Extract tags from frontmatter. Handles list, inline-list, and single-string forms."""
    tags = fm.get('tags') or fm.get('tag') or []
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(t) for t in tags if t]
    return []


def strip_body(text: str) -> str:
    """Return note body with frontmatter removed. Wikilink search runs on this."""
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def extract_links(body: str) -> tuple[list[str], list[str], list[str]]:
    """
    Return (wikilinks, note_embeds, asset_embeds) — deduplicated, order-preserving.
    """
    def dedup(seq: Iterable[str]) -> list[str]:
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    wikilinks = dedup(m.strip() for m in WIKILINK_RE.findall(body))
    all_embeds = dedup(m.strip() for m in EMBED_RE.findall(body))

    note_embeds = []
    asset_embeds = []
    for e in all_embeds:
        _, ext = os.path.splitext(e)
        if ext and ext.lower() != '.md':
            asset_embeds.append(e)
        else:
            note_embeds.append(e)

    return wikilinks, note_embeds, asset_embeds


# ── Vault walking ──────────────────────────────────────────────────────────
def find_notes(vault: Path, exclude_dirs: set[str]) -> list[Path]:
    """
    Recursively find all .md files, skipping any file whose path contains
    a directory component matching exclude_dirs.
    """
    notes = []
    for md in vault.rglob('*.md'):
        rel_parts = md.relative_to(vault).parts
        if any(part in exclude_dirs for part in rel_parts):
            continue
        notes.append(md)
    return sorted(notes)


def icloud_prefetch(vault: Path) -> None:
    """Ask iCloud to download any offloaded files. macOS-only. Best-effort."""
    try:
        subprocess.run(
            ['brctl', 'download', str(vault)],
            check=False,
            timeout=120,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


# ── Index build ────────────────────────────────────────────────────────────
def build_index(vault: Path, exclude_dirs: set[str]) -> dict:
    """Parse every note and assemble the full index dict."""
    note_paths = find_notes(vault, exclude_dirs)

    # First pass: title -> path map.
    notes_by_title: dict[str, Path] = {}
    duplicates = []
    for p in note_paths:
        title = p.stem
        if title in notes_by_title:
            duplicates.append({
                'title': title,
                'paths': [
                    str(notes_by_title[title].relative_to(vault)),
                    str(p.relative_to(vault)),
                ],
            })
        else:
            notes_by_title[title] = p

    def resolve_target(target: str) -> Optional[str]:
        """
        Try to resolve a wikilink target to a real note title.
        Handles path-style [[folder/Note]] and .md-suffixed [[Note.md]].
        Returns canonical title, or None if unresolvable.
        """
        if target.lower().endswith('.md'):
            target = target[:-3]
        if target in notes_by_title:
            return target
        if '/' in target:
            basename = target.rsplit('/', 1)[-1]
            if basename in notes_by_title:
                return basename
        return None

    # Second pass: parse notes.
    parsed = []
    for p in note_paths:
        try:
            text = p.read_text(encoding='utf-8', errors='replace')
        except (OSError, IOError) as e:
            print(f'! could not read {p}: {e}', file=sys.stderr)
            continue

        fm = parse_frontmatter(text)
        body = strip_body(text)
        wikilinks, note_embeds, asset_embeds = extract_links(body)

        parsed.append({
            'rel_path': str(p.relative_to(vault)),
            'title': p.stem,
            'tags': normalize_tags(fm),
            'wikilinks': wikilinks,
            'note_embeds': note_embeds,
            'asset_embeds': asset_embeds,
        })

    # Third pass: edges + broken links.
    edges = []
    broken_links = []
    in_degree: Counter = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)

    for note in parsed:
        source = note['title']
        for target in note['wikilinks']:
            resolved = resolve_target(target)
            if resolved is not None:
                edges.append({'source': source, 'target': resolved, 'type': 'wikilink'})
                in_degree[resolved] += 1
                adjacency[source].add(resolved)
                adjacency[resolved].add(source)
            else:
                broken_links.append({'source': source, 'target': target, 'type': 'wikilink'})

        for target in note['note_embeds']:
            resolved = resolve_target(target)
            if resolved is not None:
                edges.append({'source': source, 'target': resolved, 'type': 'embed'})
                in_degree[resolved] += 1
                adjacency[source].add(resolved)
                adjacency[resolved].add(source)
            else:
                broken_links.append({'source': source, 'target': target, 'type': 'embed'})

    all_titles = set(notes_by_title.keys())
    has_outgoing = {n['title'] for n in parsed if any(
        resolve_target(t) is not None for t in n['wikilinks'] + n['note_embeds']
    )}
    orphans = sorted(t for t in all_titles if in_degree[t] == 0 and t not in has_outgoing)

    hubs = [{'title': t, 'in_degree': d} for t, d in in_degree.most_common(20)]

    visited: set[str] = set()
    components = []
    for title in all_titles:
        if title in visited:
            continue
        stack = [title]
        component = set()
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            component.add(n)
            stack.extend(adjacency[n] - visited)
        components.append(len(component))
    components.sort(reverse=True)

    tag_counts: Counter = Counter()
    for note in parsed:
        for tag in note['tags']:
            tag_counts[tag] += 1

    return {
        'vault_path': str(vault),
        'note_count': len(parsed),
        'notes': parsed,
        'edges': edges,
        'broken_links': broken_links,
        'orphans': orphans,
        'hubs': hubs,
        'components': components,
        'tag_counts': dict(tag_counts.most_common()),
        'duplicate_titles': duplicates,
        'excluded_dirs': sorted(exclude_dirs),
    }


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description='Index an Obsidian vault.')
    parser.add_argument('vault_path', help='Path to the vault root directory')
    parser.add_argument('--out', default='', help='Output JSON file (default: stdout)')
    parser.add_argument('--exclude-dir', action='append', default=[],
                        help="Additional directory name to exclude (can be repeated)")
    parser.add_argument('--include-default-excluded', action='store_true',
                        help="Ignore the built-in exclude list (index __Templates etc.)")
    parser.add_argument('--skip-download', action='store_true',
                        help="Skip 'brctl download'")
    args = parser.parse_args()

    vault = Path(args.vault_path).expanduser().resolve()
    if not vault.is_dir():
        print(f'! not a directory: {vault}', file=sys.stderr)
        return 1

    exclude_dirs = set() if args.include_default_excluded else set(DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(args.exclude_dir)

    if not args.skip_download:
        print(f'. prefetching iCloud content for {vault}', file=sys.stderr)
        icloud_prefetch(vault)

    print(f'. indexing {vault}', file=sys.stderr)
    print(f'. excluding: {sorted(exclude_dirs) or "(nothing)"}', file=sys.stderr)
    index = build_index(vault, exclude_dirs)

    print(f'. {index["note_count"]} notes', file=sys.stderr)
    print(f'. {len(index["edges"])} edges', file=sys.stderr)
    print(f'. {len(index["broken_links"])} broken links', file=sys.stderr)
    print(f'. {len(index["orphans"])} orphans', file=sys.stderr)
    print(f'. {len(index["duplicate_titles"])} duplicate titles', file=sys.stderr)
    if index['components']:
        print(f'. {len(index["components"])} components (largest: {index["components"][0]})',
              file=sys.stderr)

    output = json.dumps(index, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(output, encoding='utf-8')
        print(args.out)
    else:
        print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())