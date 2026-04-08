"""CLI entry point for graph-context."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click

from . import config
from .storage.store import GraphStore
from .indexer.structure import StructureIndexer
from .indexer.history import HistoryIndexer
from .indexer import git_ops


@click.group()
@click.option("--repo", default=".", help="Path to the repository root.")
@click.pass_context
def cli(ctx: click.Context, repo: str) -> None:
    """graph-context: Graph-based codebase understanding for coding agents."""
    ctx.ensure_object(dict)
    ctx.obj["repo"] = str(Path(repo).resolve())


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize graph-context in the current repository."""
    repo = ctx.obj["repo"]
    project_dir = config.get_project_dir(repo)
    project_dir.mkdir(parents=True, exist_ok=True)

    meta = config.load_meta(repo)
    if not meta:
        config.save_meta(repo, {"initialized": True, "last_commit": None})
        click.echo(f"Initialized graph-context in {project_dir}")
    else:
        click.echo(f"graph-context already initialized in {project_dir}")


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--incremental", is_flag=True, help="Only index changed files.")
@click.option("--layer", type=click.Choice(["structure", "history", "planning", "all"]), default="all")
@click.pass_context
def index(ctx: click.Context, incremental: bool, layer: str) -> None:
    """Index the codebase into the graph."""
    repo = ctx.obj["repo"]
    db_path = config.get_db_path(repo)
    meta = config.load_meta(repo)

    with GraphStore(db_path) as store:
        if layer in ("structure", "all"):
            indexer = StructureIndexer(store, repo)
            t0 = time.time()

            if incremental and meta.get("last_commit"):
                stats = indexer.index_incremental(meta["last_commit"])
                mode = "incremental"
            else:
                stats = indexer.index_full()
                mode = "full"

            elapsed = time.time() - t0
            click.echo(
                f"Structure index ({mode}): "
                f"{stats['files_indexed']} files, "
                f"{stats['nodes_created']} nodes, "
                f"{stats['edges_created']} edges "
                f"({elapsed:.2f}s)"
            )

        if layer in ("history", "all"):
            if git_ops.is_git_repo(repo):
                hist_indexer = HistoryIndexer(store, repo)
                t0 = time.time()

                since = meta.get("last_history_commit") if incremental else None
                hist_stats = hist_indexer.index(since_hash=since)

                elapsed = time.time() - t0
                click.echo(
                    f"History index: "
                    f"{hist_stats['commits']} commits, "
                    f"{hist_stats['changes']} changes, "
                    f"{hist_stats['affects']} affects, "
                    f"{hist_stats['co_changes']} co-change edges "
                    f"({elapsed:.2f}s)"
                )
            else:
                click.echo("History index: skipped (not a git repo)")

        # TODO: planning indexer

    # Update meta
    head = git_ops.get_head_hash(repo) if git_ops.is_git_repo(repo) else None
    if layer in ("structure", "all"):
        meta["last_commit"] = head
    if layer in ("history", "all"):
        meta["last_history_commit"] = head
    config.save_meta(repo, meta)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@cli.group()
@click.pass_context
def query(ctx: click.Context) -> None:
    """Query the codebase graph."""
    pass


@query.command("definition")
@click.argument("symbol")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_definition(ctx: click.Context, symbol: str, fmt: str) -> None:
    """Find where a symbol is defined."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            """
            MATCH (n:Function)
            WHERE n.name = $name
            RETURN 'function' AS kind, n.name AS name, n.file_path AS file, n.line_start AS line, n.signature AS sig
            UNION ALL
            MATCH (n:Class)
            WHERE n.name = $name
            RETURN 'class' AS kind, n.name AS name, n.file_path AS file, n.line_start AS line, '' AS sig
            UNION ALL
            MATCH (n:Variable)
            WHERE n.name = $name
            RETURN 'variable' AS kind, n.name AS name, n.file_path AS file, n.line_start AS line, '' AS sig
            """,
            {"name": symbol},
        )
        _output(rows, ["kind", "name", "file", "line", "signature"], fmt)


@query.command("callers")
@click.argument("symbol")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_callers(ctx: click.Context, symbol: str, fmt: str) -> None:
    """Find what calls a function."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            """
            MATCH (caller:Function)-[:CALLS]->(callee:Function)
            WHERE callee.name = $name
            RETURN caller.name AS caller, caller.file_path AS file, caller.line_start AS line
            """,
            {"name": symbol},
        )
        _output(rows, ["caller", "file", "line"], fmt)


@query.command("callees")
@click.argument("symbol")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_callees(ctx: click.Context, symbol: str, fmt: str) -> None:
    """Find what a function calls."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            """
            MATCH (caller:Function)-[:CALLS]->(callee:Function)
            WHERE caller.name = $name
            RETURN callee.name AS callee, callee.file_path AS file, callee.line_start AS line
            """,
            {"name": symbol},
        )
        _output(rows, ["callee", "file", "line"], fmt)


@query.command("imports")
@click.argument("file")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_imports(ctx: click.Context, file: str, fmt: str) -> None:
    """Show what a file imports."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            "MATCH (f:File {path: $fp})-[:IMPORTS]->(target:File) RETURN target.path AS imported_file",
            {"fp": file},
        )
        _output(rows, ["imported_file"], fmt)


@query.command("module")
@click.argument("path")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_module(ctx: click.Context, path: str, fmt: str) -> None:
    """Show the structure of a module."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            """
            MATCH (f:File)-[:BELONGS_TO]->(m:Module {path: $mp})
            OPTIONAL MATCH (f)-[:CONTAINS_FUNC]->(fn:Function)
            OPTIONAL MATCH (f)-[:CONTAINS_CLASS]->(cls:Class)
            RETURN f.path AS file,
                   collect(DISTINCT fn.name) AS functions,
                   collect(DISTINCT cls.name) AS classes
            """,
            {"mp": path},
        )
        _output(rows, ["file", "functions", "classes"], fmt)


@query.command("blast-radius")
@click.argument("symbol")
@click.option("--depth", default=5, help="Max traversal depth.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_blast_radius(ctx: click.Context, symbol: str, depth: int, fmt: str) -> None:
    """Find everything that transitively depends on a symbol."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            f"""
            MATCH (target:Function {{name: $name}})<-[:CALLS*1..{depth}]-(caller:Function)
            RETURN DISTINCT caller.name AS dependent, caller.file_path AS file
            """,
            {"name": symbol},
        )
        _output(rows, ["dependent", "file"], fmt)


@query.command("cycles")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_cycles(ctx: click.Context, fmt: str) -> None:
    """Detect circular dependencies between files."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema(layers=("structure",))
        rows = store.query(
            """
            MATCH (a:File)-[:IMPORTS*2..6]->(a)
            RETURN DISTINCT a.path AS file_in_cycle
            """,
        )
        _output(rows, ["file_in_cycle"], fmt)


# ---------------------------------------------------------------------------
# history queries
# ---------------------------------------------------------------------------

@query.command("recent")
@click.argument("path")
@click.option("--since", default="30", help="Number of days to look back (default: 30).")
@click.option("--limit", "max_results", default=20, help="Max results.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_recent(ctx: click.Context, path: str, since: str, max_results: int, fmt: str) -> None:
    """Show recent changes to a file or module."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        # Try as a file first, then as a module path prefix
        rows = store.query(
            """
            MATCH (f:File)-[:CHANGED_IN]->(c:Commit)
            WHERE f.path STARTS WITH $path OR f.path = $path
            RETURN f.path AS file, c.message AS commit_message,
                   c.author AS author, c.timestamp AS timestamp
            ORDER BY c.timestamp DESC
            LIMIT $lim
            """,
            {"path": path, "lim": max_results},
        )
        _output(rows, ["file", "commit_message", "author", "timestamp"], fmt)


@query.command("co-changes")
@click.argument("file")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_co_changes(ctx: click.Context, file: str, fmt: str) -> None:
    """Show files that frequently change together with a given file."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        rows = store.query(
            """
            MATCH (f:File {path: $fp})-[r:CO_CHANGES_WITH]->(other:File)
            RETURN other.path AS co_changed_file, r.count AS times
            ORDER BY r.count DESC
            """,
            {"fp": file},
        )
        _output(rows, ["co_changed_file", "times"], fmt)


@query.command("churn")
@click.argument("path")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_churn(ctx: click.Context, path: str, fmt: str) -> None:
    """Show most frequently changed files in a module/directory."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        rows = store.query(
            """
            MATCH (f:File)-[:CHANGED_IN]->(c:Commit)
            WHERE f.path STARTS WITH $path
            RETURN f.path AS file, count(c) AS changes
            ORDER BY changes DESC
            """,
            {"path": path},
        )
        _output(rows, ["file", "changes"], fmt)


@query.command("authors")
@click.argument("path")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_authors(ctx: click.Context, path: str, fmt: str) -> None:
    """Show who has worked on a file or module."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        rows = store.query(
            """
            MATCH (f:File)-[:CHANGED_IN]->(c:Commit)
            WHERE f.path STARTS WITH $path OR f.path = $path
            RETURN c.author AS author, count(c) AS commits
            ORDER BY commits DESC
            """,
            {"path": path},
        )
        _output(rows, ["author", "commits"], fmt)


@query.command("affected-symbols")
@click.argument("commit_hash")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def query_affected_symbols(ctx: click.Context, commit_hash: str, fmt: str) -> None:
    """Show which functions/classes were affected by a commit."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        rows = store.query(
            """
            MATCH (c:Commit {hash: $hash})-[:INCLUDES]->(ch:Change)-[:AFFECTS_FUNC]->(fn:Function)
            RETURN 'function' AS kind, fn.name AS name, fn.file_path AS file, ch.file_path AS changed_file
            UNION ALL
            MATCH (c:Commit {hash: $hash})-[:INCLUDES]->(ch:Change)-[:AFFECTS_CLASS]->(cls:Class)
            RETURN 'class' AS kind, cls.name AS name, cls.file_path AS file, ch.file_path AS changed_file
            """,
            {"hash": commit_hash},
        )
        _output(rows, ["kind", "name", "file", "changed_file"], fmt)


# ---------------------------------------------------------------------------
# cypher (escape hatch)
# ---------------------------------------------------------------------------

@cli.command("cypher")
@click.argument("query_str")
@click.pass_context
def raw_cypher(ctx: click.Context, query_str: str) -> None:
    """Execute a raw Cypher query."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        rows = store.query(query_str)
        for row in rows:
            click.echo(row)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command("stats")
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show graph statistics."""
    repo = ctx.obj["repo"]
    with GraphStore(config.get_db_path(repo)) as store:
        store.ensure_schema()
        for label in ("File", "Module", "Function", "Class", "Type", "Variable", "Endpoint", "Event", "Schema", "Commit", "Change", "Plan", "Intent"):
            rows = store.query(f"MATCH (n:{label}) RETURN count(n)")
            count = rows[0][0] if rows else 0
            if count > 0:
                click.echo(f"  {label:12s} {count:>6d}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _output(rows: list[list], columns: list[str], fmt: str) -> None:
    """Format and print query results."""
    if not rows:
        click.echo("(no results)")
        return

    if fmt == "json":
        data = [dict(zip(columns, row)) for row in rows]
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        # Simple table format
        widths = [len(c) for c in columns]
        for row in rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val)))

        header = "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
        click.echo(header)
        click.echo("  ".join("-" * w for w in widths))
        for row in rows:
            line = "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row))
            click.echo(line)
