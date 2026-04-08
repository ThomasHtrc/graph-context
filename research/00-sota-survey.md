# SOTA Survey: Graph Structures for Coding Agent Workflows

> Compiled 2026-04-08. Sources: academic papers, open-source projects, and practical implementations through mid-2025.

---

## Executive Summary

The field has converged on a clear winning pattern: **graph-based retrieval + LLM generation**. Rather than using GNNs to generate code directly, the most effective systems build a code graph, use it to select/rank relevant context, and feed that context to a frontier LLM. Tree-sitter is the de facto standard for parsing, and even simple graph approaches (like aider's PageRank over a file↔symbol bipartite graph) dramatically improve agent performance on multi-file tasks.

### Key Insight for This Project

A coding agent doesn't need a perfect, fully-resolved type-level graph. A "good enough" graph built from tree-sitter (handling ~90% of cases without full type resolution) provides most of the value at a fraction of the complexity. The single most impactful feature is **context ranking**: given a task, which files and symbols should the LLM see?

---

## 1. GraphRAG & Knowledge Graphs

### Microsoft GraphRAG (2024)
- **Paper**: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization" (Edge et al., arXiv:2404.16130)
- **Pipeline**: Chunk text → LLM extracts entities/relationships → build weighted graph → Leiden community detection (hierarchical) → LLM summarizes each community
- **Two query modes**: Global search (maps to community summaries, good for "what are the themes?") and Local search (entity-centric, graph-augmented retrieval)
- **Key innovation**: Hierarchical community summaries enable corpus-level sensemaking that vector-RAG cannot do
- **Weakness**: Expensive batch indexing (many LLM calls). Not designed for rapidly-changing data

### Notable Derivatives
| Project | Key Improvement |
|---------|----------------|
| **LightRAG** (HKUDS) | Skips community detection; dual-level retrieval (entity + relationship). Cheaper |
| **nano-graphrag** | Minimal ~800-line reimplementation for experimentation |
| **Fast GraphRAG** (circlemind-ai) | PageRank-based retrieval instead of full community detection; incremental updates |
| **DRIFT Search** (Microsoft) | Iterative query refinement through the graph |

### Relevance to Our Project
GraphRAG's community detection maps well to codebases — communities = subsystems/features/layers. Community summarization could auto-generate module-level documentation. But the batch indexing model is wrong for code; we need **incremental updates** (more like Graphiti's model).

---

## 2. Graph-Based Agent Memory

### Zep's Graphiti
- **Repo**: `github.com/getzep/graphiti`
- Temporal knowledge graph for agent memory. Each interaction is an "episode" that extracts entities/relationships
- **Temporal awareness**: every node/edge has valid_from/valid_to timestamps — tracks how facts change
- **Entity resolution**: LLM-based merging of references to the same entity
- **Key difference from GraphRAG**: designed for streaming/incremental updates, not batch indexing

### Mem0
- Open-source memory layer with graph support (Neo4j backend)
- Builds user-centric knowledge graphs from conversations

### Key Design Patterns
1. **Entity-centric graphs**: nodes = entities, edges = relationships (good for personal assistants)
2. **Event-centric graphs**: nodes include events/episodes linked to entities (good for task-oriented agents)
3. **Hierarchical summarization**: detailed low-level + summarized high-level memories
4. **Decay and consolidation**: weight by recency/relevance, implement forgetting

---

## 3. Code-Specific Graph Approaches

### Representing a Codebase as a Graph — Consensus Multi-Layer Model

| Layer | Nodes | Edges | Use Case |
|-------|-------|-------|----------|
| **File/Module** | Files, directories | imports, includes | "What files are related?" |
| **Symbol** | Functions, classes, methods, variables | calls, inheritance, implements, field-access | "What calls this function?" |
| **Data Flow** | Values, assignments | assignments, parameter passing, returns | "Where does this data go?" |
| **History** (optional) | Commits, changes | co-change relationships (from git) | "What usually changes together?" |

### Key Implementations

#### Aider's RepoMap (most influential practical implementation)
- **Repo**: `github.com/Aider-AI/aider` → `aider/repomap.py`
- Uses tree-sitter to parse all files, extracts "tags" (definitions + references)
- Builds a bipartite graph: files ↔ symbols
- Runs **PageRank** to rank files/symbols by structural importance, boosted by chat context
- Generates a condensed text map (file paths + indented function/class signatures), sized to fit token budget
- **Strengths**: Simple, fast, language-agnostic, handles 10K+ file repos
- **Limitations**: No data-flow edges, no type resolution, name-based matching only

#### Sourcegraph Cody (most precise)
- Uses SCIP (successor to LSIF) for compiler-grade code intelligence
- Precise cross-repo code navigation (definitions, references, implementations)
- **Strength**: Most precise code graph of any coding assistant
- **Limitation**: SCIP indexers only exist for a subset of languages

#### AutoCodeRover
- Gives the LLM AST-based search APIs (search_class, search_method, search_code)
- Navigates the codebase structurally rather than with text search
- **Finding**: Structured code search significantly outperforms grep-based search for bug localization

#### Other Notable Tools
- **CodeQL** (GitHub): Datalog-based queries over code graphs. Gold standard for "if I change this, what breaks?" but heavy (minutes to build DB)
- **Joern**: Code Property Graphs (CPG) combining AST, CFG, and PDG. Uses OverflowDB
- **Stack Graphs** (GitHub): Formalism for name resolution across files/languages
- **ast-grep**: CLI tool for structural search/replace using tree-sitter
- **dependency-cruiser**, **madge**: JS/TS dependency graph tools

---

## 4. Academic Research Highlights

### Key Papers

| Paper | Year | Key Contribution |
|-------|------|-----------------|
| GraphCodeBERT (Guo et al.) | 2021 | Data flow edges in pre-training — established that graph structure helps code understanding |
| CodePlan (Bairi et al., Microsoft) | 2023 | Dependency-aware multi-file editing. Order of edits matters for cross-cutting changes |
| RepoBench (Liu et al.) | 2023 | Benchmark for cross-file completion. Finding: cross-file retrieval quality is the bottleneck |
| RepoFusion (Shrivastava et al.) | 2023 | Fusion of 5-10 structurally relevant files outperforms top-k embedding-retrieved files |
| Agentless (Xia et al.) | 2024 | Hierarchical localization (repo → file → class → method). A "skeleton" view is surprisingly effective |
| AutoCodeRover (Zhang et al.) | 2024 | AST-based search APIs for agents outperform text search |
| Long Code Arena (Bogomolov et al.) | 2024 | Even with 100K+ context windows, dumping a whole repo performs worse than intelligent 10-20K token selection |

### Key Findings

1. **Graph distance > embedding similarity for code**. A function 2 hops away in the call graph is almost always more relevant than a textually similar function in an unrelated module.

2. **The "concentric circles" pattern**: Start with focal point → direct dependencies → indirect dependencies, filling context budget greedily.

3. **Signatures > implementations**: 50 related function signatures are more useful than 5 full implementations, for most tasks.

4. **Hybrid retrieval wins**: Graph distance + embedding similarity + recency + user-intent signals. No single signal dominates.

5. **LLMs can't do multi-hop reasoning alone**: Impact analysis, change propagation, and "what depends on X?" queries require graph traversal. LLMs reason about results but can't reliably compute transitive closures.

6. **The tool-use pattern works best**: LLMs are good at deciding which graph edges to follow but bad at holding full graphs in context. Traverse one hop at a time via tool calls.

---

## 5. Agentic Workflow Orchestration (Control Flow Graphs)

### LangGraph
- Directed graphs define agent control flow. Nodes = state-transforming functions, edges = static or conditional routing
- Built-in checkpointing for pause/resume, human-in-the-loop, fault tolerance
- Key patterns: ReAct loop, Plan-and-Execute, Multi-Agent, Map-Reduce

### Important Distinction
Two meanings of "graph" in this space:
- **Knowledge/context graphs**: data structures storing entities and relationships (what we're primarily building)
- **Workflow/orchestration graphs**: control flow for agent execution (LangGraph, CrewAI)

The most sophisticated systems use both: a knowledge graph for context retrieval, orchestrated by a workflow graph.

---

## 6. Storage & Implementation Options

### Comparison

| Storage | Setup Cost | Query Power | Traversals | Persistence | Best For |
|---------|-----------|-------------|------------|-------------|----------|
| **Neo4j** | High (server+JVM) | Excellent (Cypher) | Excellent | Built-in | Large enterprise codebases |
| **NetworkX** | Low (pip) | Good (algorithms) | Excellent | Manual serialize | Prototyping, analysis |
| **SQLite adjacency** | Zero | Good (SQL+CTE) | Decent | Built-in | Production CLI tools |
| **JSON file** | Zero | Manual | Manual | Built-in | Small graphs (<5K nodes) |
| **Markdown** | Zero | Manual | Manual | Built-in | Human-readable, <1K nodes |

### Recommended: SQLite with Adjacency Lists

```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- 'file', 'function', 'class', 'module', 'variable'
    name TEXT NOT NULL,
    file_path TEXT,
    line_start INTEGER,
    line_end INTEGER,
    metadata TEXT  -- JSON blob
);
CREATE TABLE edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'imports', 'calls', 'defines', 'inherits', 'contains'
    metadata TEXT,
    PRIMARY KEY (source_id, target_id, type),
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_file ON nodes(file_path);
```

**Why SQLite**: Zero-dependency, single file, fast reads via indexes, handles millions of rows, portable across languages, built-in FTS5 for full-text search. Recursive CTEs handle 3-5 hop traversals in 10-50ms on 100K nodes.

### Recommended Hybrid Storage

1. **SQLite** as canonical store (fast queries, incremental updates, indexed)
2. **JSON export** for interop and backup (dump subgraphs on demand)
3. **Markdown summaries** per-module for LLM context injection (LLM-native format)

---

## 7. Incremental Updates

### Recommended: Git-Based Change Detection

```bash
# Get files changed since last graph update
git diff --name-only $LAST_COMMIT_HASH HEAD
git diff --name-only HEAD  # uncommitted changes
git ls-files --others --exclude-standard  # new untracked files
```

Store last-processed commit hash in the graph DB metadata. Per-file update cost: <50ms (tree-sitter parse: 1-10ms, SQLite update: 5-20ms).

### Update Strategy
1. Compare current file hashes against stored ones
2. Changed files: delete all nodes/edges from that file, re-parse, re-insert
3. Deleted files: remove all associated nodes/edges
4. New files: parse and insert

---

## 8. Query Patterns for a Coding Agent

### Tier 1: Navigation (most common)
- "What does function X depend on?" → outgoing edges from X
- "What depends on function X?" → incoming edges to X
- "Where is symbol X defined?" → node lookup by name

### Tier 2: Architecture
- "What's the architecture of module X?" → subgraph extraction under a directory
- "What are the most important files?" → PageRank / betweenness centrality
- "Show me the class hierarchy" → follow extends/implements edges

### Tier 3: Change Impact
- "If I change function X, what might break?" → transitive reverse dependency closure
- "What's the blast radius of this change?" → count of transitive dependents
- "Are there circular dependencies?" → cycle detection

### Tier 4: LLM Context Assembly
- "Give me the most relevant N files for task T" → rank by graph proximity + recency + mentions
- "What's the minimal context to understand function X?" → X's definition + direct callees + containing class
- "Summarize module X" → extract public API + key dependencies + containment hierarchy

---

## 9. Proposed Architecture for graph-context

```
graph-context/
  src/
    parser/          # tree-sitter based, per-language extractors
    storage/         # SQLite-backed graph store
    query/           # query API (navigation, architecture, impact)
    export/          # JSON, markdown, DOT exporters
    sync/            # git-based incremental updates
    context/         # LLM context assembly (ranking, summarization)
  .graph-context.db  # SQLite database (gitignored)
```

### Implementation Phases
1. **File-level dependency graph** — parse imports/exports, store in SQLite. Enables "what files are related to X?"
2. **Symbol-level graph** — extract functions/classes and call/reference relationships. Enables "what calls this function?"
3. **Incremental updates** — git diff-based change detection. Makes it fast enough for interactive use
4. **LLM context assembly** — use graph to rank/select relevant code for prompts. Generate per-module markdown summaries
5. **Change impact analysis** — "if I modify X, what might break?"
6. **Semantic enrichment** — LLM-generated summaries as node attributes, community detection for subsystem identification

---

## 10. Key Open-Source Repositories

| Project | URL | Relevance |
|---------|-----|-----------|
| Aider | `github.com/Aider-AI/aider` | RepoMap — the most proven code graph approach |
| Microsoft GraphRAG | `github.com/microsoft/graphrag` | Community detection + hierarchical summarization |
| Graphiti (Zep) | `github.com/getzep/graphiti` | Temporal graph memory for agents |
| LightRAG | `github.com/HKUDS/LightRAG` | Simplified GraphRAG |
| Fast GraphRAG | `github.com/circlemind-ai/fast-graphrag` | PageRank-based, incremental |
| nano-graphrag | `github.com/gusye1234/nano-graphrag` | Minimal reference implementation |
| LangGraph | `github.com/langchain-ai/langgraph` | Agent orchestration via graphs |
| Sourcegraph SCIP | `github.com/sourcegraph/scip` | Precise code intelligence protocol |
| tree-sitter | `github.com/tree-sitter/tree-sitter` | Foundation for parsing |
| ast-grep | `github.com/ast-grep/ast-grep` | Structural code search |
