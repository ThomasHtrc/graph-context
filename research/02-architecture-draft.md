# Architecture Draft: graph-context

> Draft v3 — 2026-04-08. Adds full inter-function data flow model (endpoints, events, schemas, shared state).

---

## What Are We Trying to Build?

A tool that builds and maintains a **graph representation of a codebase** so that coding agents (Claude Code, Cursor, aider, etc.) can:

1. **Navigate** — "Where is X defined? What calls it? What does it depend on?"
2. **Understand architecture** — "What are the subsystems? How do they relate? What does this function accept and return?"
3. **Assess impact** — "If I change X, what might break?"
4. **Retrieve optimal context** — "For this task, what's the most relevant code to show the LLM?"
5. **Understand history** — "What changed recently? What files change together? Why did this evolve?"
6. **Plan ahead** — "What's planned for this module? What's the intended direction?"

The tool is **not** an agent itself — it's a **service layer** that agents query.

---

## What Do We Graph?

### Graph Layers

The graph is organized in three layers that can be built and queried independently:

```
┌─────────────────────────────────────────────┐
│          Layer 3: Planning                   │
│   Plans, Intents, Milestones, Proposals      │
│   (agent-written, human-curated)             │
├─────────────────────────────────────────────┤
│          Layer 2: History                    │
│   Commits, Changes, CoChange patterns        │
│   (derived from git)                         │
├─────────────────────────────────────────────┤
│          Layer 1: Structure                  │
│   Files, Modules, Classes, Functions, Types  │
│   (derived from code via tree-sitter)        │
└─────────────────────────────────────────────┘
```

### Layer 1: Structure (code as it exists now)

#### Node Types

| Node Type | What It Represents | Key Properties |
|-----------|-------------------|----------------|
| **File** | A source file | `path`, `lang`, `hash`, `last_modified` |
| **Module** | A logical module/package (directory or namespace) | `path`, `name` |
| **Class** | A class, struct, interface, trait, enum | `name`, `file_path`, `line_start`, `line_end`, `visibility` |
| **Function** | A function, method, or lambda | `name`, `file_path`, `line_start`, `line_end`, `signature`, `visibility`, `is_method` |
| **Type** | A type alias, generic type, or interface | `name`, `file_path`, `line_start`, `line_end` |
| **Variable** | A module-level constant or exported variable | `name`, `file_path`, `line_start`, `line_end` |
| **Endpoint** | An API route, HTTP handler, RPC method, CLI command | `path` (route pattern), `method` (GET/POST/...), `name`, `file_path`, `line_start`, `line_end` |
| **Event** | A named event, signal, message topic, or queue channel | `name`, `channel`, `file_path` |
| **Schema** | A DB model, table definition, protobuf message, GraphQL type | `name`, `file_path`, `line_start`, `line_end`, `store_type` (sql/nosql/proto/graphql) |

#### Edge Types — Structural

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **IMPORTS** | File → File | File A imports from file B |
| **CONTAINS** | File → Class/Function/Type/Variable/Endpoint/Schema | File defines this symbol at top level |
| **HAS_METHOD** | Class → Function | Class defines this method |
| **CALLS** | Function → Function | Function A calls function B |
| **INHERITS** | Class → Class | Class A extends/implements class B |
| **USES_TYPE** | Function/Variable → Type/Class | References this type in signature or body |
| **BELONGS_TO** | File → Module | File is part of this module/package |
| **DEPENDS_ON** | Module → Module | Module A depends on module B (aggregated from IMPORTS) |

#### Edge Types — Data Flow (Inter-Function)

These edges capture how data moves *between* functions and across system boundaries — the three decoupling mechanisms that pure call-graph analysis misses.

**Function I/O:**

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **EXPECTS** | Function → Type/Class | Function accepts this type as a parameter |
| **RETURNS** | Function → Type/Class | Function produces/returns this type |
| **YIELDS** | Function → Type/Class | Generator/async iterator produces values of this type |

The **EXPECTS/RETURNS** edges are distinct from USES_TYPE because they carry directional data-flow semantics. Knowing that `processOrder(order: Order) → Receipt` accepts an `Order` and returns a `Receipt` is far more useful for an agent than just knowing it "uses" both types.

**Shared State:**

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **READS** | Function → Variable | Function reads a module-level/global variable, config, or cache |
| **WRITES** | Function → Variable | Function mutates shared state |

**Event-Driven Flow:**

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **EMITS** | Function → Event | Function dispatches/publishes an event or message |
| **HANDLES** | Function → Event | Function listens for/subscribes to an event |

**Persistence Boundaries:**

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **READS_FROM** | Function → Schema | Function queries/reads from this data store |
| **WRITES_TO** | Function → Schema | Function inserts/updates/deletes in this data store |
| **MAPS_TO** | Class/Type → Schema | This application type corresponds to this DB table/schema |

**API Boundaries:**

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **EXPOSES** | File/Module → Endpoint | This module defines this API route |
| **ROUTE_HANDLER** | Endpoint → Function | This function handles requests to this endpoint |
| **MIDDLEWARE** | Endpoint → Function | This middleware/interceptor runs before the handler |

#### Data Flow Queries Enabled

```cypher
-- "What functions can produce an Order for me to pass to processOrder?"
MATCH (f:Function)-[:RETURNS]->(t:Type {name: 'Order'})
RETURN f.name, f.file_path

-- "What functions consume the Receipt that processOrder returns?"
MATCH (f:Function)-[:EXPECTS]->(t:Type {name: 'Receipt'})
RETURN f.name, f.file_path

-- "Trace the data pipeline: what transforms Order into something else?"
MATCH (f:Function)-[:EXPECTS]->(input:Type {name: 'Order'}),
      (f)-[:RETURNS]->(output:Type)
WHERE output.name <> 'Order'
RETURN f.name, input.name AS consumes, output.name AS produces

-- "Trace a full request: HTTP → handler → processing → DB → events"
MATCH (ep:Endpoint {path: '/api/orders'})-[:ROUTE_HANDLER]->(handler:Function),
      (handler)-[:CALLS*1..5]->(fn:Function)
WHERE (fn)-[:WRITES_TO]->(:Schema) OR (fn)-[:EMITS]->(:Event)
RETURN ep.path, handler.name, fn.name, 
       [(fn)-[:WRITES_TO]->(s:Schema) | s.name] AS writes,
       [(fn)-[:EMITS]->(e:Event) | e.name] AS emits

-- "What happens when this event fires?"
MATCH (emitter:Function)-[:EMITS]->(ev:Event {name: 'order.placed'}),
      (listener:Function)-[:HANDLES]->(ev)
RETURN emitter.name AS trigger, listener.name AS handler, listener.file_path

-- "What reads/writes shared state?" (potential race conditions)
MATCH (writer:Function)-[:WRITES]->(v:Variable)<-[:READS]-(reader:Function)
WHERE writer <> reader
RETURN v.name, writer.name AS writer, reader.name AS reader

-- "What's the full data lifecycle of an Order?"
MATCH (ep:Endpoint)-[:ROUTE_HANDLER]->(h:Function)-[:CALLS*0..5]->(fn:Function)
WHERE (fn)-[:EXPECTS]->(:Type {name: 'Order'}) OR (fn)-[:RETURNS]->(:Type {name: 'Order'})
   OR (fn)-[:READS_FROM]->(:Schema {name: 'orders'}) OR (fn)-[:WRITES_TO]->(:Schema {name: 'orders'})
RETURN ep.path, fn.name,
       [(fn)-[:EXPECTS]->(t) | t.name] AS inputs,
       [(fn)-[:RETURNS]->(t) | t.name] AS outputs,
       [(fn)-[:READS_FROM]->(s) | s.name] AS reads,
       [(fn)-[:WRITES_TO]->(s) | s.name] AS writes

-- "What middleware protects this endpoint?"
MATCH (ep:Endpoint {path: '/api/admin'})-[:MIDDLEWARE]->(mw:Function)
RETURN mw.name, mw.file_path

-- "Map the full request pipeline for an endpoint"
MATCH (ep:Endpoint {path: '/api/orders'})-[:MIDDLEWARE]->(mw:Function)
MATCH (ep)-[:ROUTE_HANDLER]->(handler:Function)
RETURN ep.path, ep.method, 
       collect(DISTINCT mw.name) AS middleware_chain,
       handler.name AS handler
```

#### Auto-Extractability

| Component | Auto-extractable? | How |
|-----------|-------------------|-----|
| **Endpoints** | Mostly — decorator/annotation patterns (`@app.route`, `@Get()`, `@router.post`) | Tree-sitter + framework-specific decorator pattern matching |
| **Schemas** | Mostly — ORM model classes, migration files, protobuf/GraphQL definitions | Tree-sitter + class-inherits-from-Model patterns |
| **Events** | Partially — `emit("name")` / `on("name")` / `@EventHandler` patterns | Pattern matching on known event framework APIs; string-based names need heuristics |
| **READS/WRITES** | Yes — assignment vs. reference to module-level symbols | Tree-sitter scope analysis (write = assignment target, read = value reference) |
| **READS_FROM/WRITES_TO** | Partially — ORM calls (`.query()`, `.save()`, `.find()`) are patterned; raw SQL harder | Framework-specific method call patterns |
| **Middleware** | Mostly — registration patterns (`app.use()`, `@UseGuard()`) are framework-specific but regular | Decorator/call pattern matching |
| **EXPECTS/RETURNS** | Yes — from type annotations; partial for untyped code | Tree-sitter parameter/return type extraction |
| **YIELDS** | Yes — `yield` / `yield from` / `async for` patterns | Tree-sitter AST node matching |
| **MAPS_TO** | Partially — ORM `__tablename__`, decorators like `@Entity('table')` | Framework-specific patterns |

For components that can't be fully auto-extracted, the system supports **hint files** (`.graph-context/hints.yaml`) where developers or agents can declare what the extractor can't infer:

```yaml
# .graph-context/hints.yaml
events:
  - name: "order.placed"
    emitted_by: ["src/orders/service.ts::placeOrder"]
    handled_by: ["src/notifications/email.ts::sendConfirmation", "src/analytics/tracker.ts::trackOrder"]

schemas:
  - name: "orders"
    mapped_from: "src/models/order.ts::Order"
    
endpoints:
  - path: "/api/webhooks/stripe"
    handler: "src/payments/webhook.ts::handleStripeWebhook"
```

### Layer 2: History (how the code evolved)

#### Node Types

| Node Type | What It Represents | Key Properties |
|-----------|-------------------|----------------|
| **Commit** | A git commit | `hash`, `message`, `author`, `timestamp` |
| **Change** | A file-level change within a commit | `file_path`, `additions`, `deletions`, `change_type` (add/modify/delete) |

#### Edge Types

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **CHANGED_IN** | File → Commit | File was modified in this commit |
| **INCLUDES** | Commit → Change | Commit contains this change |
| **AFFECTS** | Change → Function/Class | This change touched this symbol (line-range overlap) |
| **CO_CHANGES_WITH** | File → File | Files frequently change together | Properties: `count`, `correlation` |
| **PARENT** | Commit → Commit | Git parent relationship |

#### Key Queries Enabled

```cypher
-- "What files usually change together with auth.ts?"
MATCH (f:File {path: 'src/auth.ts'})-[r:CO_CHANGES_WITH]->(other:File)
RETURN other.path, r.count ORDER BY r.count DESC LIMIT 10

-- "What functions were recently modified?"
MATCH (c:Commit)-[:INCLUDES]->(ch:Change)-[:AFFECTS]->(fn:Function)
WHERE c.timestamp > datetime('2026-04-01')
RETURN fn.name, fn.file_path, c.message, c.timestamp
ORDER BY c.timestamp DESC

-- "What's the churn rate of this module?" (frequently changing = unstable)
MATCH (f:File)-[:BELONGS_TO]->(m:Module {name: 'auth'}),
      (f)-[:CHANGED_IN]->(c:Commit)
WHERE c.timestamp > datetime('2026-01-01')
RETURN f.path, count(c) AS changes ORDER BY changes DESC

-- "Who has been working on this area?"
MATCH (f:File)-[:BELONGS_TO]->(m:Module {name: 'auth'}),
      (f)-[:CHANGED_IN]->(c:Commit)
RETURN c.author, count(c) AS commits ORDER BY commits DESC
```

#### How It's Built
- **On full index**: Walk `git log` for the last N commits (configurable, default ~500), extract file-level changes, compute co-change correlations
- **On incremental index**: Process new commits since last indexed hash
- **AFFECTS edges**: Compare change line ranges against known symbol line ranges from Layer 1
- **CO_CHANGES_WITH**: Computed periodically (not per-commit) — count file pairs that appear in the same commit, normalize by frequency

### Layer 3: Planning (where the code is going)

This layer stores **agent-written or human-curated** information about intended future state. It's what makes this tool more than a static analyzer — agents can record plans and retrieve them later, across sessions.

#### Node Types

| Node Type | What It Represents | Key Properties |
|-----------|-------------------|----------------|
| **Plan** | A planned change or feature | `title`, `description`, `status` (draft/active/completed/abandoned), `created_at`, `updated_at`, `author` |
| **Intent** | A specific intended modification | `description`, `rationale`, `status` |

#### Edge Types

| Edge Type | From → To | What It Means |
|-----------|-----------|---------------|
| **TARGETS** | Plan → File/Module/Class/Function | This plan involves changing this entity |
| **IMPLEMENTS** | Intent → Plan | This intent is part of this plan |
| **DEPENDS_ON_PLAN** | Plan → Plan | This plan should be done after that plan |
| **SUPERSEDES** | Plan → Plan | This plan replaces that plan |

#### Key Queries Enabled

```cypher
-- "What's planned for the auth module?"
MATCH (p:Plan)-[:TARGETS]->(f:File)-[:BELONGS_TO]->(m:Module {name: 'auth'})
WHERE p.status IN ['draft', 'active']
RETURN p.title, p.description, collect(f.path) AS affected_files

-- "Before I change this function, are there any plans I should know about?"
MATCH (p:Plan)-[:TARGETS]->(fn:Function {name: 'handleAuth'})
WHERE p.status IN ['draft', 'active']
RETURN p.title, p.description, p.rationale

-- "What's the intended order of work?"
MATCH (p1:Plan)-[:DEPENDS_ON_PLAN]->(p2:Plan)
WHERE p1.status = 'active'
RETURN p1.title, p2.title AS blocked_by

-- "What plans are now completed?" (agent marks done after implementation)
MATCH (p:Plan)-[:TARGETS]->(entity)
WHERE p.status = 'active'
AND ALL(target IN [(p)-[:TARGETS]->(t) | t] 
    WHERE EXISTS { MATCH (target)-[:CHANGED_IN]->(c:Commit) 
                   WHERE c.timestamp > p.created_at })
RETURN p.title  -- candidates for marking completed
```

#### How It's Built
- **Agent-written**: Agents create Plan/Intent nodes via CLI commands (`graph-context plan create`, `graph-context plan link`)
- **Human-curated**: Plans can be defined in a `.graph-context/plans/` directory as YAML/markdown files, ingested on index
- **Status lifecycle**: draft → active → completed/abandoned. Agents can update status.
- **Linking**: Plans are linked to structural nodes via TARGETS edges. This is what makes them queryable in context — "show me plans related to what I'm working on."

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     CLI Interface                         │
│               graph-context <command>                      │
│                                                            │
│   index | query | context | map | plan | history           │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  ┌───────────┐  ┌──────────┐  ┌────────────────────────┐ │
│  │  Indexer   │  │  Query   │  │  Context Generator     │ │
│  │           │  │  Engine   │  │                        │ │
│  │ structure │  │          │  │  rank (PageRank +       │ │
│  │ history   │  │  Cypher  │  │    recency + co-change) │ │
│  │ plans     │  │  queries │  │  assemble context       │ │
│  │           │  │          │  │  export md/json          │ │
│  └─────┬─────┘  └────┬─────┘  └──────────┬─────────────┘ │
│        │              │                    │               │
│  ┌─────▼──────────────▼────────────────────▼────────────┐ │
│  │               LadybugDB (embedded)                    │ │
│  │               .graph-context/db/                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌────────────────────┐  ┌───────────────────────────┐   │
│  │  Tree-sitter        │  │  Git Interface            │   │
│  │  Parsers            │  │  log, diff, blame         │   │
│  └────────────────────┘  └───────────────────────────┘   │
│                                                            │
├──────────────────────────────────────────────────────────┤
│  Future: MCP Server wrapper (same query engine)           │
└──────────────────────────────────────────────────────────┘
```

### Components

#### 1. Indexer

Three sub-indexers, one per layer:

**Structure Indexer** (Layer 1):
- Full index: parse every file → tree-sitter AST → extract symbols + relationships → populate LadybugDB
- Incremental: `git diff` against stored commit hash → update only changed files
- Per-file cost: <50ms (parse: 1-10ms, extract: 5-15ms, DB write: 5-20ms)

**History Indexer** (Layer 2):
- Walks `git log`, extracts commits + file-level changes
- Computes AFFECTS edges by overlapping change line ranges with symbol line ranges
- Computes CO_CHANGES_WITH by counting file co-occurrence in commits
- Incremental: only process commits since last indexed hash

**Plan Indexer** (Layer 3):
- Ingests plans from `.graph-context/plans/*.yaml` files
- Resolves TARGETS edges by matching entity references to structural nodes
- Also supports programmatic creation via CLI/API

#### 2. Query Engine

Thin Cypher-backed layer with codebase-specific methods:

```python
# Navigation
graph.definition("handleRequest")
graph.callers("handleRequest")
graph.callees("handleRequest")
graph.type_flow("handleRequest")          # → what it EXPECTS and RETURNS

# Architecture
graph.module_structure("src/auth")
graph.class_hierarchy("BaseService")
graph.cycles()

# Data Flow
graph.data_pipeline("Order")              # → trace EXPECTS/RETURNS chains across functions
graph.event_flow("order.placed")          # → who emits, who handles
graph.endpoint_trace("/api/orders")       # → middleware → handler → calls → DB/events
graph.shared_state_users("config")        # → who READS/WRITES this variable
graph.schema_usage("orders")              # → who READS_FROM/WRITES_TO this schema

# Impact
graph.blast_radius("handleRequest")
graph.affected_files(["src/auth/login.ts"])

# History
graph.recent_changes("src/auth", since="7d")
graph.co_change_partners("src/auth/login.ts")
graph.churn("src/auth")

# Plans
graph.plans_for("src/auth")
graph.active_plans()
graph.plan_dependencies("migrate-to-v2")

# Context (for LLM prompt assembly)
graph.relevant_context("handleRequest", budget=8000)
graph.module_summary("src/auth")
graph.repo_map(focus=["src/auth/login.ts"], budget=4000)
```

#### 3. Context Generator

Uses all three layers to produce optimized context for LLM prompts.

**Ranking algorithm** (multi-signal):
1. Start with "focal" nodes — files/symbols mentioned in the task
2. Compute personalized PageRank from focal nodes over the structural graph
3. Boost by **recency** — recently modified files get higher weight (from Layer 2)
4. Boost by **co-change** — files that frequently change with focal files (from Layer 2)
5. Include **active plans** targeting focal area (from Layer 3)
6. Fill token budget in descending rank order
7. Prefer signatures over implementations (more info per token)

**Output formats:**
- **Markdown map** — file paths + indented signatures + plan annotations, sized to fit budget
- **JSON structured** — for programmatic consumption
- **Annotated context** — code snippets with graph-derived metadata (callers count, change frequency, active plans)

---

## CLI Design

```bash
# === Indexing ===
graph-context init                          # initialize .graph-context/ in current repo
graph-context index                         # full index (all three layers)
graph-context index --incremental           # update only what changed
graph-context index --layer structure       # index only structural layer
graph-context index --layer history         # index only history layer

# === Navigation Queries ===
graph-context query definition <symbol>
graph-context query callers <symbol>
graph-context query callees <symbol>
graph-context query imports <file>
graph-context query type-flow <symbol>      # EXPECTS/RETURNS chain

# === Architecture Queries ===
graph-context query module <path>           # module structure overview
graph-context query hierarchy <class>       # class hierarchy
graph-context query cycles                  # circular dependencies

# === Data Flow Queries ===
graph-context query pipeline <type>         # trace type through EXPECTS/RETURNS chains
graph-context query event <event-name>      # who emits, who handles
graph-context query endpoint <route>        # full request trace: middleware → handler → deps
graph-context query shared-state <variable> # who reads/writes this variable
graph-context query schema <schema-name>    # who reads from / writes to this store
graph-context query request-map <route>     # full visual: endpoint → processing → persistence → events

# === Impact Queries ===
graph-context query blast-radius <symbol>
graph-context query affected <file> [<file>...]

# === History Queries ===
graph-context query recent <path> [--since 7d]
graph-context query co-changes <file>
graph-context query churn <path>

# === Plans ===
graph-context plan create <title> --targets <file/symbol>...
graph-context plan list [--status active]
graph-context plan show <plan-id>
graph-context plan update <plan-id> --status completed
graph-context plan link <plan-id> --targets <file/symbol>...

# === Context Generation ===
graph-context context --focus <file/symbol>... --budget <tokens>
graph-context map --focus <path> --budget <tokens>
graph-context summary <module-path>

# === Raw Cypher (escape hatch) ===
graph-context cypher "MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.name = 'main' RETURN g"

# === Output formatting (global flags) ===
--format json|markdown|table              # default: table for terminal, markdown for piped output
```

---

## Directory Structure

```
graph-context/
├── src/
│   └── graph_context/
│       ├── __init__.py
│       ├── cli.py                  # click/typer CLI entry point
│       ├── indexer/
│       │   ├── __init__.py
│       │   ├── structure.py        # Layer 1: tree-sitter → symbols → graph
│       │   ├── history.py          # Layer 2: git log → commits/changes → graph
│       │   ├── plans.py            # Layer 3: plan files → plan nodes → graph
│       │   ├── extractors/         # per-language + per-framework extraction
│       │   │   ├── __init__.py
│       │   │   ├── base.py         # BaseExtractor interface (language-level)
│       │   │   ├── base_framework.py  # BaseFrameworkExtractor (data flow)
│       │   │   ├── python.py
│       │   │   ├── typescript.py
│       │   │   ├── javascript.py
│       │   │   └── frameworks/     # framework-specific data flow extractors
│       │   │       ├── __init__.py  # auto-detection from project deps
│       │   │       ├── flask.py
│       │   │       ├── django.py
│       │   │       ├── sqlalchemy.py
│       │   │       ├── express.py
│       │   │       ├── nestjs.py
│       │   │       ├── prisma.py
│       │   │       └── eventemitter.py
│       │   └── git_ops.py          # git diff, log, blame operations
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── schema.py           # LadybugDB CREATE TABLE statements
│       │   └── store.py            # connection management, read/write ops
│       ├── query/
│       │   ├── __init__.py
│       │   ├── navigation.py       # definition, callers, callees, type-flow
│       │   ├── architecture.py     # module structure, hierarchy, cycles
│       │   ├── dataflow.py         # pipelines, events, endpoints, shared state, schemas
│       │   ├── impact.py           # blast radius, affected files
│       │   └── history.py          # recent changes, co-changes, churn
│       ├── context/
│       │   ├── __init__.py
│       │   ├── ranker.py           # multi-signal relevance ranking
│       │   ├── assembler.py        # token-budget-aware context assembly
│       │   └── formatter.py        # markdown, JSON, table output
│       ├── plans/
│       │   ├── __init__.py
│       │   └── manager.py          # CRUD for plan nodes
│       └── config.py               # project-level configuration
├── tests/
│   ├── fixtures/                   # sample repos for testing
│   ├── test_indexer/
│   ├── test_query/
│   ├── test_context/
│   └── test_plans/
├── .graph-context/                 # per-project data (gitignored, except plans/ and hints.yaml)
│   ├── db/                         # LadybugDB database directory (gitignored)
│   ├── plans/                      # plan definitions (YAML, committable)
│   ├── hints.yaml                  # manual declarations for events, schemas, endpoints (committable)
│   └── meta.json                   # last indexed commit, config, stats
├── pyproject.toml
├── README.md
└── research/                       # this research folder
```

---

## Language Support: Python + TypeScript/JavaScript First

Extraction happens at two levels: **language extractors** (universal structure) and **framework extractors** (framework-specific patterns for data flow).

### Language Extractors

Each language needs an extractor that maps tree-sitter AST node types to our core structural model:

| Concept | Python tree-sitter nodes | TypeScript tree-sitter nodes |
|---------|-------------------------|------------------------------|
| Function def | `function_definition` | `function_declaration`, `arrow_function`, `method_definition` |
| Class def | `class_definition` | `class_declaration` |
| Import | `import_statement`, `import_from_statement` | `import_statement`, `import_clause` |
| Function call | `call` | `call_expression` |
| Type annotation | `type` (in parameter/return) | `type_annotation`, `type_alias_declaration` |
| Inheritance | `argument_list` of class def | `heritage_clause` |
| Yield | `yield` expression | `yield_expression` |
| Variable def | `assignment` (module-level) | `variable_declaration` (module-level, `const`/`let`) |

Adding a new language = implementing the `BaseExtractor` interface for that language's tree-sitter grammar.

### Framework Extractors (Data Flow)

Framework-specific patterns for extracting Endpoint, Event, Schema, and data flow edges. These are composable — a project can use multiple framework extractors:

| Framework | Language | What It Extracts |
|-----------|----------|-----------------|
| **Flask/FastAPI** | Python | Endpoints (`@app.route`, `@router.get`), middleware |
| **Django** | Python | Endpoints (urlpatterns), Schemas (Models), READS_FROM/WRITES_TO (ORM querysets) |
| **SQLAlchemy** | Python | Schemas (declarative models), MAPS_TO, READS_FROM/WRITES_TO |
| **Express/Fastify** | TS/JS | Endpoints (`app.get()`, `router.post()`), middleware (`app.use()`) |
| **NestJS** | TS | Endpoints (`@Get()`, `@Post()`), Events (`@EventPattern()`), middleware (`@UseGuards()`) |
| **Prisma** | TS | Schemas (from `.prisma` file), READS_FROM/WRITES_TO (client method calls) |
| **TypeORM/Sequelize** | TS | Schemas (`@Entity()`), MAPS_TO, READS_FROM/WRITES_TO |
| **EventEmitter** | TS/JS | Events (`.emit("name")`, `.on("name")`) |
| **Celery/Bull** | Python/TS | Events/tasks (`.delay()`, `.add()`, `@task`) |

Framework extractors are optional and auto-detected from project dependencies (package.json, pyproject.toml, requirements.txt). Adding a new framework = implementing the `BaseFrameworkExtractor` interface.

```
src/graph_context/indexer/extractors/
├── base.py                    # BaseExtractor interface (language-level)
├── base_framework.py          # BaseFrameworkExtractor interface (data flow)
├── python.py                  # Python language extractor
├── typescript.py              # TypeScript language extractor
├── javascript.py              # JavaScript language extractor
└── frameworks/
    ├── __init__.py            # auto-detection from project deps
    ├── flask.py
    ├── django.py
    ├── sqlalchemy.py
    ├── express.py
    ├── nestjs.py
    ├── prisma.py
    └── eventemitter.py
```

---

## What We Deliberately Exclude (for now)

- **Intra-function data flow** — too granular, expensive to compute
- **Control flow graphs** — same; lives inside functions
- **Test coverage mapping** — interesting but separate concern
- **Fully dynamic relationships** — can't determine statically (but we do capture event patterns and framework-specific conventions which cover the most common "dynamic" flows)
- **Embedding/vector index** — out of scope for v1; pure structural + history graph

---

## MCP Upgrade Path

The CLI and MCP server share the same query engine. When ready to upgrade:

```python
# The query engine is the same object
engine = GraphQueryEngine(db_path=".graph-context/db")

# CLI calls it directly
@cli.command()
def callers(symbol: str):
    results = engine.callers(symbol)
    print(format(results))

# MCP server wraps it as tools
@mcp.tool()
def graph_callers(symbol: str) -> str:
    results = engine.callers(symbol)
    return format_for_llm(results)
```

The query engine is the invariant; CLI and MCP are just different frontends.

---

## Open Design Questions

1. **Plan file format** — YAML? Markdown with frontmatter? Should plans be committable to the repo?
2. **Token counting** — tiktoken for accuracy, or char/4 heuristic for speed? Configurable?
3. **Co-change computation** — how many commits to look back? Configurable threshold for "frequently"?
4. **Monorepo support** — configurable module boundary detection? Or infer from package.json/pyproject.toml?
5. **External dependencies** — record as "external" nodes with no internal structure? Or ignore entirely?
