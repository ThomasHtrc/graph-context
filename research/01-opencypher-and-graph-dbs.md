# OpenCypher, GQL, and Compatible Graph Databases

> Compiled 2026-04-08. Focus: what fits a local CLI tool for coding agents.

---

## 1. OpenCypher Overview

OpenCypher is the open-source specification of the Cypher query language, originally developed by Neo4j and donated to the community in 2015. It defines a declarative, pattern-matching language for property graphs.

### OpenCypher vs Neo4j's Cypher
- **OpenCypher** specifies the core: `MATCH`, `WHERE`, `RETURN`, `CREATE`, `MERGE`, `DELETE`, variable-length paths, aggregation, list comprehensions, `UNION`
- **Neo4j extensions** (not in openCypher): APOC library, full-text index management, `CALL {} IN TRANSACTIONS`, admin commands, RBAC syntax

### Spec Status
Last major release: **openCypher 9**. The project is now pivoting to incrementally integrate **ISO GQL** features, effectively converging openCypher toward GQL. No further independent major versions expected.

---

## 2. Why Cypher Over SQL for Code Graphs

### Where Cypher Dramatically Wins

**Variable-length path traversals:**
```cypher
-- All transitive dependencies of module 'auth', up to 10 hops
MATCH (m:Module {name: 'auth'})-[:IMPORTS*1..10]->(dep:Module)
RETURN DISTINCT dep.name
```
vs SQL (10 lines of recursive CTE with manual depth tracking)

**Shortest path:**
```cypher
-- Shortest import chain from file A to file B
MATCH p = shortestPath(
  (a:File {path: 'src/auth.ts'})-[:IMPORTS*]->(b:File {path: 'src/db.ts'})
)
RETURN [n IN nodes(p) | n.path] AS chain
```
SQL equivalent: 15+ lines with fragile string-based cycle prevention, no guaranteed shortest path

**Cycle detection:**
```cypher
-- Find circular dependencies
MATCH (a:Module)-[:IMPORTS*2..]->(a)
RETURN DISTINCT a.name
```
SQL: Notoriously difficult. SQLite has no built-in cycle detection in recursive CTEs.

**Multi-relationship pattern matching:**
```cypher
-- Classes inheriting from Base that override method 'process'
MATCH (c:Class)-[:INHERITS]->(base:Class {name: 'Base'}),
      (c)-[:DEFINES]->(m:Function {name: 'process'}),
      (base)-[:DEFINES]->(bm:Function {name: 'process'})
RETURN c.name, c.file_path
```
SQL: Wall of 6+ JOINs with aliases. Cypher reads like a diagram.

### Where SQL is Fine
Simple 1-hop queries ("what does X call?", "where is X defined?") are equally readable in both. SQL wins for aggregation-heavy analytics.

---

## 3. Compatible Databases — Full Landscape

### Tier 1: Major Server-Based Implementations

| Database | Cypher Support | License | Embedding? | Notes |
|----------|---------------|---------|------------|-------|
| **Neo4j** | Full Cypher (superset) | Community: AGPLv3+Commons Clause; Enterprise: Commercial | No (JVM server) | Too heavy for CLI tool |
| **Memgraph** | Full openCypher, spec contributor | BSL 1.1 | No (C++ server) | Very fast, but server-required |
| **FalkorDB** | openCypher (RedisGraph successor) | Source-available | No (Redis module) | Sub-10ms latency, but needs Redis |
| **Apache AGE** | openCypher grammar | Apache 2.0 | No (PG extension) | Needs running PostgreSQL |
| **Amazon Neptune** | openCypher + Gremlin | Proprietary | No (cloud) | Cloud-only |

### Tier 2: Embedded/Lightweight (Most Relevant)

| Database | Cypher? | License | Footprint | Bindings | Status |
|----------|---------|---------|-----------|----------|--------|
| **LadybugDB** (Kùzu fork) | Yes (Cypher) | MIT | ~20-50MB lib | Python, Node, Rust, Go, Java, C++, Swift, WASM | **Active**, v0.15.3 (Apr 2026) |
| **Bighorn** (Kùzu fork) | Yes (Cypher) | MIT | Similar | Multiple | Active, integrated with GraphXR |
| **DuckDB + DuckPGQ** | No (SQL/PGQ, Cypher-inspired) | MIT | ~30MB | Python, Node, Rust, etc. | Extension maturing |
| **GraphLite** | No (GQL, not Cypher) | Open source | Small (Rust) | TBD | Very early stage |
| **ArcadeDB** | Yes (97.8% TCK) | Apache 2.0 | Large (JVM) | Multiple | Mature but heavy |

### RedisGraph: Dead (EOL January 2025). FalkorDB is the community successor.

### Kùzu: Acquired by Apple (October 2025). Repo archived at v0.11.3.

---

## 4. Kùzu / LadybugDB Deep Dive

### What Kùzu Was
Embedded property graph database from University of Waterloo — "SQLite for graphs":
- In-process library, no server
- Columnar storage with CSR adjacency indices
- Cypher-compatible query language
- Directory-based storage (not single file, like DuckDB)
- Benchmarked on LDBC-SF100 (280M nodes, 1.7B edges)

### LadybugDB (Most Active Fork)
- **Install**: `pip install real_ladybug`
- **Version**: v0.15.3 (April 2026), 5,740 commits, 903 stars
- **Maintainer**: Arun Sharma (ex-Facebook/Google)
- **License**: MIT
- **Full 1:1 Kùzu replacement** — same API, same Cypher dialect

### Cypher Features Supported
- `MATCH`, `WHERE`, `RETURN`, `WITH`, `UNWIND`
- `CREATE`, `MERGE`, `SET`, `DELETE`
- Variable-length paths: `-[:REL*1..5]->`
- Shortest path queries
- Aggregations, `ORDER BY`, `LIMIT`, `SKIP`
- List comprehensions, `CASE` expressions

### Key Difference from Neo4j
Kùzu/LadybugDB requires **predeclared schema** (`CREATE NODE TABLE`, `CREATE REL TABLE`). This is actually an advantage for a code graph — our schema is known upfront:

```cypher
CREATE NODE TABLE File (path STRING, lang STRING, hash STRING, PRIMARY KEY (path));
CREATE NODE TABLE Function (id STRING, name STRING, file_path STRING, line_start INT64, line_end INT64, signature STRING, PRIMARY KEY (id));
CREATE NODE TABLE Class (id STRING, name STRING, file_path STRING, line_start INT64, line_end INT64, PRIMARY KEY (id));
CREATE NODE TABLE Module (path STRING, name STRING, PRIMARY KEY (path));

CREATE REL TABLE IMPORTS (FROM File TO File);
CREATE REL TABLE CALLS (FROM Function TO Function);
CREATE REL TABLE DEFINES (FROM File TO Function);
CREATE REL TABLE CONTAINS (FROM Class TO Function);
CREATE REL TABLE INHERITS (FROM Class TO Class);
```

### Footprint
- Library: ~20-50MB depending on platform
- Database directory: low MB range for a 100K-node code graph
- Memory: disk-based with in-memory caching, much lighter than Neo4j/Memgraph

---

## 5. ISO GQL Standard

### Status
**ISO/IEC 39075:2024** — published April 12, 2024. First new database query language ISO standard since SQL (1987).

### Relationship to OpenCypher
- GQL was **heavily influenced by Cypher** — pattern matching syntax is ~95% identical
- Also incorporates ideas from PGQL (Oracle) and G-CORE (academic)
- OpenCypher project is now converging toward GQL compliance
- **SQL/PGQ** (SQL:2023) is GQL's companion for embedding graph queries in SQL

### Current Adoption
- Neo4j Cypher 25: converging toward GQL
- Google Spanner Graph: native GQL
- GraphLite: full GQL 2024
- DuckDB DuckPGQ: SQL/PGQ
- Microsoft Fabric: GQL announced

### Implication
Building on Cypher now and migrating to GQL later would be low-friction (~95% syntax overlap).

---

## 6. Comparison for Our Use Case

### Requirements
- Local CLI tool, no server
- Small footprint
- Code graph (files, functions, classes, modules + relationships)
- Multi-hop traversals (dependencies, call chains, impact analysis)
- Incremental updates

### Options Ranked

| | SQLite | LadybugDB | DuckDB+DuckPGQ |
|---|--------|-----------|----------------|
| **Server needed** | No | No | No |
| **Footprint** | ~1MB | ~20-50MB | ~30MB |
| **Graph queries** | Recursive CTEs (verbose) | Native Cypher (elegant) | SQL/PGQ (middle ground) |
| **Multi-hop traversals** | Painful past 3 hops | First-class | Decent |
| **Shortest path** | Very hard | Built-in | Not yet |
| **Cycle detection** | Very hard | Trivial | TBD |
| **Maturity** | Bulletproof | Good (v0.15.3, Kùzu lineage) | Extension still maturing |
| **Risk** | Zero | Community fork sustainability | Extension stability |
| **Ecosystem** | Universal | Growing | Large (DuckDB) |

### Recommendation

**LadybugDB is the best fit** if we want Cypher expressiveness with an embedded model. The queries we need (transitive deps, shortest paths, cycle detection, impact analysis) are exactly where Cypher shines over SQL.

**Pragmatic path**: Start with LadybugDB directly. The schema is known, the queries are well-defined, and the library is MIT-licensed with active maintenance. Keep SQLite as a fallback if LadybugDB proves problematic — the data model (nodes + edges) translates trivially between them.

**DuckDB + DuckPGQ** is the alternative if we want to bet on a more established project, trading some graph query elegance for ecosystem stability.
