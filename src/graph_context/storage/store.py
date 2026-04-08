"""Graph store: connection management and core operations over LadybugDB."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import real_ladybug as lbug

from . import schema


class GraphStore:
    """Manages a LadybugDB graph database for a project."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db: lbug.Database | None = None
        self._conn: lbug.Connection | None = None

    # -- lifecycle ------------------------------------------------------------

    def open(self) -> None:
        """Open (or create) the database."""
        self._db = lbug.Database(str(self._db_path))
        self._conn = lbug.Connection(self._db)

    def close(self) -> None:
        """Close the database connection."""
        self._conn = None
        self._db = None

    def __enter__(self) -> GraphStore:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def conn(self) -> lbug.Connection:
        if self._conn is None:
            raise RuntimeError("Store not open — call .open() or use as context manager")
        return self._conn

    # -- schema ---------------------------------------------------------------

    def ensure_schema(self, layers: tuple[str, ...] = ("structure", "history", "planning")) -> None:
        """Create all tables for the requested layers (idempotent)."""
        stmts: list[str] = []
        if "structure" in layers:
            stmts += schema.STRUCTURE_NODE_TABLES + schema.STRUCTURE_REL_TABLES
        if "history" in layers:
            stmts += schema.HISTORY_NODE_TABLES + schema.HISTORY_REL_TABLES
        if "planning" in layers:
            stmts += schema.PLANNING_NODE_TABLES + schema.PLANNING_REL_TABLES
        for stmt in stmts:
            self.conn.execute(stmt)

    # -- query helpers --------------------------------------------------------

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> lbug.QueryResult:
        """Execute a Cypher statement and return the raw QueryResult."""
        if params:
            return self.conn.execute(cypher, params)
        return self.conn.execute(cypher)

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """Execute a Cypher query and return all rows as lists."""
        result = self.execute(cypher, params)
        rows: list[list[Any]] = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    def query_one(self, cypher: str, params: dict[str, Any] | None = None) -> list[Any] | None:
        """Execute a query and return the first row, or None."""
        result = self.execute(cypher, params)
        if result.has_next():
            return result.get_next()
        return None

    # -- bulk write helpers ---------------------------------------------------

    def clear_file(self, file_path: str) -> None:
        """Remove all nodes and edges originating from a given source file.

        This is used for incremental re-indexing: delete everything from the
        changed file, then re-extract and re-insert.
        """
        # Delete edges first (referencing nodes from this file), then nodes.
        # We delete symbols whose id starts with the file path.
        for node_table in ("Function", "Class", "Type", "Variable", "Endpoint", "Event", "Schema"):
            # Delete the node — LadybugDB cascades edge deletion.
            self.conn.execute(
                f"MATCH (n:{node_table}) WHERE n.file_path = $fp DETACH DELETE n",
                {"fp": file_path},
            )
        # The File node itself: detach-delete removes its edges too.
        self.conn.execute(
            "MATCH (f:File {path: $fp}) DETACH DELETE f",
            {"fp": file_path},
        )

    def upsert_file(self, path: str, lang: str, hash_: str, last_modified: str) -> None:
        """Create or update a File node."""
        self.conn.execute(
            "MERGE (f:File {path: $p}) SET f.lang = $lang, f.hash = $hash, f.last_modified = $lm",
            {"p": path, "lang": lang, "hash": hash_, "lm": last_modified},
        )

    def upsert_module(self, path: str, name: str) -> None:
        """Create or update a Module node."""
        self.conn.execute(
            "MERGE (m:Module {path: $p}) SET m.name = $name",
            {"p": path, "name": name},
        )

    def create_function(
        self,
        id_: str,
        name: str,
        file_path: str,
        line_start: int,
        line_end: int,
        signature: str = "",
        visibility: str = "public",
        is_method: bool = False,
    ) -> None:
        self.conn.execute(
            """CREATE (n:Function {
                id: $id, name: $name, file_path: $fp,
                line_start: $ls, line_end: $le,
                signature: $sig, visibility: $vis, is_method: $im
            })""",
            {
                "id": id_, "name": name, "fp": file_path,
                "ls": line_start, "le": line_end,
                "sig": signature, "vis": visibility, "im": is_method,
            },
        )

    def create_class(
        self,
        id_: str,
        name: str,
        file_path: str,
        line_start: int,
        line_end: int,
        visibility: str = "public",
    ) -> None:
        self.conn.execute(
            """CREATE (n:Class {
                id: $id, name: $name, file_path: $fp,
                line_start: $ls, line_end: $le, visibility: $vis
            })""",
            {
                "id": id_, "name": name, "fp": file_path,
                "ls": line_start, "le": line_end, "vis": visibility,
            },
        )

    def create_type(
        self,
        id_: str,
        name: str,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> None:
        self.conn.execute(
            """CREATE (n:Type {
                id: $id, name: $name, file_path: $fp,
                line_start: $ls, line_end: $le
            })""",
            {"id": id_, "name": name, "fp": file_path, "ls": line_start, "le": line_end},
        )

    def create_variable(
        self,
        id_: str,
        name: str,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> None:
        self.conn.execute(
            """CREATE (n:Variable {
                id: $id, name: $name, file_path: $fp,
                line_start: $ls, line_end: $le
            })""",
            {"id": id_, "name": name, "fp": file_path, "ls": line_start, "le": line_end},
        )

    # -- edge creation helpers ------------------------------------------------

    def create_edge(self, rel_type: str, from_table: str, from_id: str, to_table: str, to_id: str, props: dict[str, Any] | None = None) -> None:
        """Create a relationship between two nodes by their primary keys.

        from_id/to_id are matched against the PK field:
          - File: path
          - Module: path
          - All others: id
        """
        from_pk = "path" if from_table in ("File", "Module") else "id"
        to_pk = "path" if to_table in ("File", "Module") else "id"

        prop_clause = ""
        params: dict[str, Any] = {"fid": from_id, "tid": to_id}
        if props:
            assignments = ", ".join(f"r.{k} = ${k}" for k in props)
            prop_clause = f" SET {assignments}"
            params.update(props)

        self.conn.execute(
            f"MATCH (a:{from_table} {{{from_pk}: $fid}}), (b:{to_table} {{{to_pk}: $tid}}) "
            f"CREATE (a)-[r:{rel_type}]->(b){prop_clause}",
            params,
        )
