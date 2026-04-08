"""File watcher: auto-reindex on file changes.

Uses watchfiles (Rust-backed) for efficient filesystem monitoring.
Debounces changes and re-indexes only modified files.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from watchfiles import watch, Change

from . import config
from .storage.store import GraphStore
from .indexer.structure import StructureIndexer, EXTRACTORS, _file_ext


# Directories to ignore
IGNORE_DIRS = {
    ".git", ".graph-context", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info",
}


def _should_watch(path: Path, repo: Path) -> bool:
    """Check if a file change should trigger reindexing."""
    # Must be a supported extension
    ext = _file_ext(str(path))
    if ext not in EXTRACTORS:
        return False
    # Must not be in an ignored directory
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return False
    for part in rel.parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return False
    return True


def run_watcher(repo_path: str, quiet: bool = False) -> None:
    """Watch a repo for file changes and auto-reindex.

    Args:
        repo_path: Path to the repository root.
        quiet: Suppress per-file output (only show summaries).
    """
    repo = Path(repo_path).resolve()
    db_path = config.get_db_path(str(repo))

    store = GraphStore(db_path)
    store.open()
    store.ensure_schema()
    indexer = StructureIndexer(store, repo)

    if not quiet:
        print(f"Watching {repo} for changes... (Ctrl+C to stop)")

    try:
        for changes in watch(
            repo,
            watch_filter=lambda change, path: _should_watch(Path(path), repo),
            debounce=1600,  # ms — batch rapid saves
            step=200,       # ms — poll interval
        ):
            # Collect unique changed file paths
            changed: set[str] = set()
            for change_type, path_str in changes:
                path = Path(path_str)
                try:
                    rel = str(path.relative_to(repo))
                except ValueError:
                    continue

                if change_type == Change.deleted:
                    store.clear_file(rel)
                    if not quiet:
                        print(f"  removed: {rel}")
                else:
                    changed.add(rel)

            if changed:
                stats = indexer.index_files(list(changed))
                if not quiet:
                    files = ", ".join(sorted(changed))
                    print(
                        f"  reindexed: {stats['files_indexed']} files "
                        f"({stats['nodes_created']} nodes, "
                        f"{stats['edges_created']} edges) "
                        f"— {files}"
                    )

    except KeyboardInterrupt:
        if not quiet:
            print("\nStopped watching.")
    finally:
        store.close()
