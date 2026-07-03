#!/usr/bin/env python3
"""
vault_index.py — Standalone Obsidian vault indexer.

Two modes:

  1. One-shot (default): parse the vault, emit JSON, exit.
       python3 vault_index.py /path/to/vault --out /tmp/index.json

  2. Long-lived (--serve): stay alive, read JSON commands from stdin,
     write JSON responses to stdout, one per line.
       python3 vault_index.py /path/to/vault --serve

     Protocol: line-delimited JSON. Each request is:
       {"id": "req-1", "method": "get_index", "params": {}}
     Response (success):
       {"id": "req-1", "result": {...}}
     Response (error):
       {"id": "req-1", "error": {"code": "...", "message": "..."}}

     Methods:
       reindex()                 — rebuild the in-memory index; return summary
       get_index()               — return cached index (auto-builds first time)
       get_note(title)           — return one note with body text
       get_backlinks(title)      — return notes that link to `title`
       get_neighbors(title,depth)— return N-hop subgraph around `title`
       search(query, in)         — search titles/tags/body for `query`
       shutdown()                — ack, then exit cleanly

Handles Obsidian quirks:
  - YAML frontmatter (list-form and inline-list-form tags)
  - Wikilinks: [[X]], [[X|alias]], [[X#section]]
  - Path-style [[folder/subfolder/Note]] resolved by basename
  - Section-only [[#section]] filtered (in-page nav)
  - Embeds ![[X]] distinguished; .md targets = note embeds, else asset
  - Directory-based exclusion (DEFAULT_EXCLUDE_DIRS)
  - iCloud offloading: `brctl download` upfront

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
DEFAULT_EXCLUDE_DIRS = {'__Templates', '_Assets', '.obsidian', '.trash'}


# ── Regexes ────────────────────────────────────────────────────────────────
WIKILINK_RE = re.compile(r'(?<!\!)\[\[([^\[\]|#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]')
EMBED_RE = re.compile(r'\!\[\[([^\[\]|#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]')
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


# ── Parsers ────────────────────────────────────────────────────────────────
def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def normalize_tags(fm: dict) -> list[str]:
    tags = fm.get('tags') or fm.get('tag') or []
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(t) for t in tags if t]
    return []


def strip_body(text: str) -> str:
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def extract_links(body: str) -> tuple[list[str], list[str], list[str]]:
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
    notes = []
    for md in vault.rglob('*.md'):
        rel_parts = md.relative_to(vault).parts
        if any(part in exclude_dirs for part in rel_parts):
            continue
        notes.append(md)
    return sorted(notes)


def icloud_prefetch(vault: Path) -> None:
    try:
        subprocess.run(
            ['brctl', 'download', str(vault)],
            check=False, timeout=120, capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


# ── Index build ────────────────────────────────────────────────────────────
def build_index(vault: Path, exclude_dirs: set[str]) -> dict:
    note_paths = find_notes(vault, exclude_dirs)

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
        if target.lower().endswith('.md'):
            target = target[:-3]
        if target in notes_by_title:
            return target
        if '/' in target:
            basename = target.rsplit('/', 1)[-1]
            if basename in notes_by_title:
                return basename
        return None

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

    edges = []
    broken_links = []
    in_degree: Counter = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)
    backlinks: dict[str, list[str]] = defaultdict(list)  # target -> [sources]

    for note in parsed:
        source = note['title']
        for target in note['wikilinks']:
            resolved = resolve_target(target)
            if resolved is not None:
                edges.append({'source': source, 'target': resolved, 'type': 'wikilink'})
                in_degree[resolved] += 1
                adjacency[source].add(resolved)
                adjacency[resolved].add(source)
                backlinks[resolved].append(source)
            else:
                broken_links.append({'source': source, 'target': target, 'type': 'wikilink'})

        for target in note['note_embeds']:
            resolved = resolve_target(target)
            if resolved is not None:
                edges.append({'source': source, 'target': resolved, 'type': 'embed'})
                in_degree[resolved] += 1
                adjacency[source].add(resolved)
                adjacency[resolved].add(source)
                backlinks[resolved].append(source)
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
        # Internal state carried forward for serve-mode methods.
        # Not intended for direct consumption; kept in the dict for reuse.
        '_notes_by_title': {t: str(p) for t, p in notes_by_title.items()},
        '_adjacency': {k: sorted(v) for k, v in adjacency.items()},
        '_backlinks': {k: sorted(set(v)) for k, v in backlinks.items()},
    }


# ── Serve mode ─────────────────────────────────────────────────────────────
class IndexServer:
    """Long-lived server. Holds one cached index; rebuilds on demand."""

    def __init__(self, vault: Path, exclude_dirs: set[str], skip_download: bool):
        self.vault = vault
        self.exclude_dirs = exclude_dirs
        self.skip_download = skip_download
        self._index: Optional[dict] = None

    def _ensure_index(self) -> dict:
        if self._index is None:
            self._reindex_inplace()
        return self._index  # type: ignore

    def _reindex_inplace(self) -> None:
        if not self.skip_download:
            icloud_prefetch(self.vault)
        self._index = build_index(self.vault, self.exclude_dirs)

    # ── Methods (called by dispatch) ────────────────────────────────────
    def reindex(self, params: dict) -> dict:
        self._reindex_inplace()
        idx = self._index  # type: ignore
        return {
            'note_count': idx['note_count'],
            'edge_count': len(idx['edges']),
            'broken_link_count': len(idx['broken_links']),
            'orphan_count': len(idx['orphans']),
            'component_count': len(idx['components']),
        }

    def get_index(self, params: dict) -> dict:
        idx = self._ensure_index()
        # Drop internal keys (leading underscore) from the client-facing view.
        return {k: v for k, v in idx.items() if not k.startswith('_')}

    def get_note(self, params: dict) -> dict:
        title = params.get('title')
        if not title:
            raise ValueError("missing 'title'")
        idx = self._ensure_index()
        notes_by_title = idx['_notes_by_title']
        if title not in notes_by_title:
            raise KeyError(f"no note titled: {title}")

        rel_path = notes_by_title[title]
        abs_path = self.vault / rel_path if not os.path.isabs(rel_path) else Path(rel_path)
        # rel_path was stored via Path.relative_to earlier — join with vault.
        try:
            text = abs_path.read_text(encoding='utf-8', errors='replace')
        except (OSError, IOError) as e:
            raise RuntimeError(f'could not read: {e}')

        fm = parse_frontmatter(text)
        body = strip_body(text)

        # Return the note's cached metadata + full body.
        note_record = next((n for n in idx['notes'] if n['title'] == title), {})
        return {
            **note_record,
            'body': body,
            'frontmatter': fm,
        }

    def get_backlinks(self, params: dict) -> dict:
        title = params.get('title')
        if not title:
            raise ValueError("missing 'title'")
        idx = self._ensure_index()
        return {'title': title, 'backlinks': idx['_backlinks'].get(title, [])}

    def get_neighbors(self, params: dict) -> dict:
        title = params.get('title')
        depth = int(params.get('depth', 1))
        if not title:
            raise ValueError("missing 'title'")
        if depth < 1:
            raise ValueError("depth must be >= 1")

        idx = self._ensure_index()
        adj = idx['_adjacency']
        if title not in adj and title not in idx['_notes_by_title']:
            raise KeyError(f"no note titled: {title}")

        # BFS out to `depth` hops.
        visited = {title}
        frontier = {title}
        for _ in range(depth):
            next_frontier = set()
            for n in frontier:
                for neighbor in adj.get(n, []):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        visited.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break

        # Return the induced subgraph.
        nodes = sorted(visited)
        node_set = set(nodes)
        sub_edges = [
            e for e in idx['edges']
            if e['source'] in node_set and e['target'] in node_set
        ]
        return {'center': title, 'depth': depth, 'nodes': nodes, 'edges': sub_edges}

    def search(self, params: dict) -> dict:
        query = params.get('query', '').lower()
        scopes = params.get('in', ['title', 'tags'])
        if not query:
            raise ValueError("missing 'query'")

        idx = self._ensure_index()
        results = []
        include_body = 'body' in scopes

        for note in idx['notes']:
            hits = []
            if 'title' in scopes and query in note['title'].lower():
                hits.append('title')
            if 'tags' in scopes and any(query in t.lower() for t in note['tags']):
                hits.append('tags')
            if include_body:
                rel = note['rel_path']
                abs_path = self.vault / rel
                try:
                    if query in abs_path.read_text(encoding='utf-8', errors='replace').lower():
                        hits.append('body')
                except OSError:
                    pass
            if hits:
                results.append({'title': note['title'], 'rel_path': note['rel_path'], 'hits': hits})

        return {'query': query, 'in': scopes, 'result_count': len(results), 'results': results}

    # ── Dispatch loop ────────────────────────────────────────────────────
    METHODS = {'reindex', 'get_index', 'get_note', 'get_backlinks',
               'get_neighbors', 'search', 'shutdown'}

    def run(self) -> int:
        print('. serve mode: waiting for requests on stdin', file=sys.stderr)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                self._respond(None, error={'code': 'invalid_request', 'message': str(e)})
                continue

            req_id = req.get('id')
            method = req.get('method')
            params = req.get('params') or {}

            if method == 'shutdown':
                self._respond(req_id, result={'status': 'shutting_down'})
                return 0

            if method not in self.METHODS:
                self._respond(req_id, error={
                    'code': 'invalid_method',
                    'message': f'unknown method: {method}',
                })
                continue

            try:
                fn = getattr(self, method)
                result = fn(params)
                self._respond(req_id, result=result)
            except (ValueError, KeyError) as e:
                self._respond(req_id, error={'code': 'bad_params', 'message': str(e)})
            except Exception as e:  # noqa: BLE001
                self._respond(req_id, error={
                    'code': 'internal_error',
                    'message': f'{type(e).__name__}: {e}',
                })
        return 0

    def _respond(self, req_id, *, result=None, error=None) -> None:
        payload = {'id': req_id}
        if error is not None:
            payload['error'] = error
        else:
            payload['result'] = result
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
        sys.stdout.flush()


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description='Index an Obsidian vault.')
    parser.add_argument('vault_path', help='Path to the vault root directory')
    parser.add_argument('--out', default='', help='Output JSON file (one-shot mode)')
    parser.add_argument('--serve', action='store_true',
                        help='Long-lived mode: read JSON commands from stdin')
    parser.add_argument('--exclude-dir', action='append', default=[],
                        help="Additional directory name to exclude (can be repeated)")
    parser.add_argument('--include-default-excluded', action='store_true',
                        help="Ignore the built-in exclude list")
    parser.add_argument('--skip-download', action='store_true',
                        help="Skip 'brctl download'")
    args = parser.parse_args()

    vault = Path(args.vault_path).expanduser().resolve()
    if not vault.is_dir():
        print(f'! not a directory: {vault}', file=sys.stderr)
        return 1

    exclude_dirs = set() if args.include_default_excluded else set(DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(args.exclude_dir)

    if args.serve:
        server = IndexServer(vault, exclude_dirs, args.skip_download)
        return server.run()

    # One-shot mode.
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

    # Drop internal keys from disk output too.
    output_index = {k: v for k, v in index.items() if not k.startswith('_')}
    output = json.dumps(output_index, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(output, encoding='utf-8')
        print(args.out)
    else:
        print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())