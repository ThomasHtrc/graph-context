# graph-context

This project uses **graph-context** — a graph-based codebase understanding tool. A graph of this codebase's structure, history, and plans is maintained in `.graph-context/db/`.

## Available MCP tools

The `graph-context` MCP server provides these tools. **Use them before reading files** — they're faster and give you ranked, relevant context.

### Context generation (use these first)
- **`context`** — Get ranked context around focal files/symbols. Use before starting any task.
  Example: `context(focus=["src/auth.py", "authenticate"], budget=4000)`
- **`repo_map`** — Get a condensed overview of the codebase or a module.
  Example: `repo_map(focus=["src/auth"], budget=8000)` or `repo_map()` for global view.

### Navigation
- **`find_definition`** — Find where a symbol is defined.
- **`find_callers`** / **`find_callees`** — Trace call relationships.
- **`blast_radius`** — Before changing a function, check what depends on it.
- **`module_structure`** — See what's in a module (files, functions, classes).

### History
- **`recent_changes`** — What changed recently in a file/module.
- **`co_changes`** — Files that frequently change together (hidden coupling).

### Plans
- **`plan_list`** / **`plan_show`** — Check existing plans before starting work.
- **`plan_create`** — Record intended changes for cross-session continuity.
- **`plan_add_intent`** — Add specific change steps to a plan.
- **`plan_update`** — Update plan status (draft → active → completed).

### Low-level
- **`graph_stats`** — Verify the graph is indexed and see codebase size.
- **`run_cypher`** — Ad-hoc Cypher queries for anything not covered above.

## Workflow

1. **Before starting work**: Call `context(focus=[...files you'll touch...])` to understand the area.
2. **Before changing a function**: Call `blast_radius(symbol="function_name")` to check impact.
3. **Check for existing plans**: Call `plan_list(status="active")` to see what's in progress.
4. **After completing work**: Update any relevant plans with `plan_update(plan_id, status="completed")`.

## Keeping the graph fresh

If you've made significant code changes, the graph may be stale. Run:
```bash
graph-context index --incremental
```
