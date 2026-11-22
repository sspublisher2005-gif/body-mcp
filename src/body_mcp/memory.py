"""Local-first persistent memory (SQLite + FTS5) for Body-MCP.

What this is: durable, inspectable notes that survive across sessions — project
conventions, verified fixes, environment limitations, user preferences.

What this is NOT: a vector database, a cloud service, or model training. Nothing
leaves the machine; the database is a plain file you can read, copy or delete.

Rules enforced in code:
  - secrets are refused (API keys, tokens, passwords) — never stored,
  - entries are scoped (project / workflow / capability / user / knowledge / research),
  - uncertain lessons are stored as `verified = 0` (proposed), never as facts,
  - updates create a new version and keep the history (`supersedes`),
  - FTS5 is used when the local SQLite build supports it, LIKE otherwise,
  - private-session browsing data is never written here.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import sqlite3
import time
import uuid

SCOPES = ("project", "workflow", "capability", "user", "knowledge", "research")
TYPES = ("note", "bugfix", "decision", "workflow", "limitation", "preference",
         "lesson", "evidence", "command", "skill")

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+token)\b\s*[:=]"),
    re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
]

MAX_CONTENT = 8000
MAX_TITLE = 200
DEFAULT_LIMIT = 20


def db_path() -> str:
    from . import permissions

    cfg = permissions._config_dir()
    os.makedirs(cfg, exist_ok=True)
    return os.path.join(cfg, "memory.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            project TEXT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            type TEXT,
            created REAL NOT NULL,
            updated REAL NOT NULL,
            source TEXT,
            confidence REAL,
            verified INTEGER DEFAULT 0,
            version INTEGER DEFAULT 1,
            supersedes TEXT,
            sensitivity TEXT DEFAULT 'normal',
            expires_at REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope, project)")
    with contextlib.suppress(sqlite3.Error):
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                           memory_id UNINDEXED, title, content, tags)""")
    conn.commit()


def fts_available() -> bool:
    try:
        conn = _connect()
        try:
            _init(conn)
            row = conn.execute("SELECT name FROM sqlite_master WHERE name='memories_fts'").fetchone()
            return row is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def looks_like_secret(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)


def _row_to_dict(row) -> dict:
    data = dict(row)
    data["tags"] = [t for t in (data.get("tags") or "").split(",") if t]
    data["verified"] = bool(data.get("verified"))
    return data


def add(*, title: str, content: str, scope: str = "project", project: str = "",
        tags: list[str] | str = "", type: str = "note", source: str = "",
        confidence: float = 0.5, verified: bool = False, sensitivity: str = "normal",
        supersedes: str = "", expires_at: float | None = None) -> dict:
    """Store one memory. Refuses secrets and unknown scopes."""
    title = (title or "").strip()[:MAX_TITLE]
    content = (content or "").strip()
    if not title or not content:
        return {"success": False, "message": "memory needs a title and content", "data": {}}
    if scope not in SCOPES:
        return {"success": False, "message": f"unknown scope {scope!r}; use one of {list(SCOPES)}",
                "data": {}}
    if type not in TYPES:
        type = "note"
    if looks_like_secret(f"{title}\n{content}"):
        return {"success": False,
                "message": "refusing to store this: it looks like a credential. "
                           "Store the fact, never the secret (e.g. 'the API key lives in the "
                           "team vault', not the key itself).",
                "data": {}}
    if len(content) > MAX_CONTENT:
        content = content[:MAX_CONTENT]
    tag_str = tags if isinstance(tags, str) else ",".join(str(t).strip() for t in tags if str(t).strip())
    memory_id = "mem_" + uuid.uuid4().hex[:12]
    now = time.time()
    conn = _connect()
    try:
        _init(conn)
        conn.execute(
            "INSERT INTO memories (id, scope, project, title, content, tags, type, created,"
            " updated, source, confidence, verified, version, supersedes, sensitivity, expires_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (memory_id, scope, project or "", title, content, tag_str, type, now, now,
             source[:200], float(confidence), 1 if verified else 0, 1,
             supersedes or None, sensitivity, expires_at))
        with contextlib.suppress(sqlite3.Error):
            conn.execute("INSERT INTO memories_fts (memory_id, title, content, tags)"
                         " VALUES (?,?,?,?)", (memory_id, title, content, tag_str))
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "message": f"memory stored ({scope})",
            "data": {"id": memory_id, "scope": scope, "verified": verified}}


def get(memory_id: str) -> dict | None:
    conn = _connect()
    try:
        _init(conn)
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def notes_dir() -> str:
    """Directory for human-editable Markdown notes (project instructions)."""
    from . import permissions

    path = os.path.join(permissions._config_dir(), "notes")
    os.makedirs(path, exist_ok=True)
    return path


def write_note(filename: str, markdown: str) -> dict:
    """Write a Markdown note you can edit by hand. Refuses credentials."""
    name = (filename or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return {"success": False, "message": "give a plain file name (e.g. conventions.md)",
                "data": {}}
    if not name.endswith(".md"):
        name += ".md"
    if looks_like_secret(markdown):
        return {"success": False, "message": "refusing to write a credential into a note",
                "data": {}}
    path = os.path.join(notes_dir(), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown[:MAX_CONTENT])
    return {"success": True, "message": f"note written to {path}", "data": {"path": path}}


def read_notes(limit: int = 20) -> list[dict]:
    """List the Markdown notes (read-only view)."""
    out = []
    try:
        names = sorted(os.listdir(notes_dir()))
    except OSError:
        return out
    for name in names[:max(1, min(limit, 50))]:
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(notes_dir(), name), encoding="utf-8") as f:
                text = f.read(4000)
        except OSError:
            continue
        out.append({"id": f"note:{name}", "scope": "notes", "type": "note",
                    "title": name, "content": text, "verified": True,
                    "source": "local markdown note"})
    return out


def search(query: str = "", scope: str | None = None, project: str = "",
           limit: int = DEFAULT_LIMIT, include_unverified: bool = True) -> list[dict]:
    """Lexical search (FTS5 when available, LIKE otherwise). Newest first."""
    limit = max(1, min(int(limit), MAX_EXPORT))
    conn = _connect()
    try:
        _init(conn)
        clauses, params = [], []
        if scope:
            clauses.append("m.scope = ?")
            params.append(scope)
        if project:
            clauses.append("m.project = ?")
            params.append(project)
        if not include_unverified:
            clauses.append("m.verified = 1")
        query = (query or "").strip()
        rows = []
        if query:
            # FTS5 MATCH treats '-', ':' etc. as operators. A query like
            # "body-mcp Linux" is a syntax error, silently swallowed below, and
            # the LIKE fallback then returned 0 rows. Quote each word token so
            # the words are searched as literals.
            import re

            fts_query = " ".join(f'"{token}"' for token in re.findall(r"\w+", query))
            if fts_query:
                with contextlib.suppress(sqlite3.Error):
                    fts_clauses = list(clauses) + ["memories_fts MATCH ?"]
                    sql = ("SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.memory_id"
                           " WHERE " + " AND ".join(fts_clauses)
                           + " ORDER BY m.updated DESC LIMIT ?")
                    rows = conn.execute(sql, params + [fts_query, limit]).fetchall()
        if not rows:
            sql = "SELECT m.* FROM memories m"
            sql_params = list(params)
            conditions = list(clauses)
            if query:
                conditions.append("(m.title LIKE ? OR m.content LIKE ? OR m.tags LIKE ?)")
                like = f"%{query}%"
                sql_params += [like, like, like]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY m.updated DESC LIMIT ?"
            rows = conn.execute(sql, sql_params + [limit]).fetchall()
        results = [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
    if scope in (None, "", "notes"):
        needle = (query or "").lower()
        for note in read_notes(limit=10):
            if not needle or needle in note["content"].lower() or needle in note["title"].lower():
                results.append(note)
    return results[:limit]


def list_scope(scope: str | None = None, project: str = "", limit: int = DEFAULT_LIMIT) -> list[dict]:
    return search("", scope=scope, project=project, limit=limit)


def update(memory_id: str, **changes) -> dict:
    """Update a memory. Creates a new version and keeps the previous one."""
    conn = _connect()
    try:
        _init(conn)
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return {"success": False, "message": f"no memory {memory_id!r}", "data": {}}
        current = _row_to_dict(row)
        title = str(changes.get("title", current["title"]))[:MAX_TITLE]
        content = str(changes.get("content", current["content"]))[:MAX_CONTENT]
        if looks_like_secret(f"{title}\n{content}"):
            return {"success": False, "message": "refusing to store a credential", "data": {}}
        tags = changes.get("tags", current["tags"])
        tag_str = ",".join(tags) if isinstance(tags, (list, tuple)) else str(tags)
        verified = changes.get("verified", current["verified"])
        confidence = changes.get("confidence", current["confidence"])
        version = int(current["version"]) + 1
        now = time.time()
        conn.execute(
            "UPDATE memories SET title=?, content=?, tags=?, verified=?, confidence=?,"
            " version=?, updated=? WHERE id=?",
            (title, content, tag_str, 1 if verified else 0, float(confidence), version, now, memory_id))
        with contextlib.suppress(sqlite3.Error):
            conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
            conn.execute("INSERT INTO memories_fts (memory_id, title, content, tags)"
                         " VALUES (?,?,?,?)", (memory_id, title, content, tag_str))
        conn.commit()
        return {"success": True, "message": f"memory updated (version {version})",
                "data": {"id": memory_id, "version": version}}
    finally:
        conn.close()


def delete(memory_id: str) -> bool:
    conn = _connect()
    try:
        _init(conn)
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        with contextlib.suppress(sqlite3.Error):
            conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear(scope: str | None = None) -> int:
    conn = _connect()
    try:
        _init(conn)
        if scope:
            cur = conn.execute("DELETE FROM memories WHERE scope = ?", (scope,))
            with contextlib.suppress(sqlite3.Error):
                conn.execute("DELETE FROM memories_fts WHERE memory_id NOT IN"
                             " (SELECT id FROM memories)")
        else:
            cur = conn.execute("DELETE FROM memories")
            with contextlib.suppress(sqlite3.Error):
                conn.execute("DELETE FROM memories_fts")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


MAX_EXPORT = 1000  # export rides the same unclamped query path as search internals


def export(scope: str | None = None, project: str = "") -> dict:
    """Export memories as JSON + Markdown so they stay human-readable."""
    items = list_scope(scope=scope, project=project, limit=MAX_EXPORT)
    markdown_lines = ["# Body-MCP memory export", ""]
    for item in items:
        flag = "verified" if item["verified"] else "proposed"
        markdown_lines.append(f"## {item['title']}  ({item['scope']}/{item['type']}, {flag})")
        markdown_lines.append(item["content"])
        if item["tags"]:
            markdown_lines.append(f"tags: {', '.join(item['tags'])}")
        markdown_lines.append("")
    return {"count": len(items), "json": items,
            "markdown": "\n".join(markdown_lines),
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def stats() -> dict:
    conn = _connect()
    try:
        _init(conn)
        rows = conn.execute("SELECT scope, COUNT(*) AS n FROM memories GROUP BY scope").fetchall()
        total = sum(r["n"] for r in rows)
        return {"total": total, "by_scope": {r["scope"]: r["n"] for r in rows},
                "path": db_path(), "fts5": fts_available(),
                "size_bytes": os.path.getsize(db_path()) if os.path.exists(db_path()) else 0}
    finally:
        conn.close()


def prune() -> int:
    """Remove entries whose expiry passed."""
    conn = _connect()
    try:
        _init(conn)
        now = time.time()
        cur = conn.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def as_json(items: list[dict]) -> str:
    return json.dumps(items, indent=2, default=str)
