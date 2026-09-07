"""Local AI file registry used by the Milestone 1 file library."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    file_type TEXT NOT NULL DEFAULT 'other',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    managed_path TEXT,
    original_path TEXT,
    source_type TEXT NOT NULL DEFAULT 'uploaded',
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_generated INTEGER NOT NULL DEFAULT 0,
    is_uploaded INTEGER NOT NULL DEFAULT 0,
    is_missing INTEGER NOT NULL DEFAULT 0,
    optional_hash TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS file_chat_links (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL,
    message_id TEXT,
    linked_at TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    PRIMARY KEY (file_id, chat_id, message_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_files_updated_at ON files(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS idx_file_links_chat ON file_chat_links(chat_id);

CREATE TABLE IF NOT EXISTS indexed_files (
    path TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    file_type TEXT NOT NULL DEFAULT 'other',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    modified_at TEXT,
    indexed_at TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    optional_hash TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    is_missing INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_indexed_filename ON indexed_files(filename);
CREATE INDEX IF NOT EXISTS idx_indexed_modified ON indexed_files(modified_at DESC);
CREATE INDEX IF NOT EXISTS idx_indexed_type ON indexed_files(file_type);

CREATE TABLE IF NOT EXISTS file_operations (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    source TEXT,
    destination TEXT,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    tool_run_id TEXT,
    chat_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_file_operations_timestamp ON file_operations(timestamp DESC);

CREATE TABLE IF NOT EXISTS tool_runs (
    tool_run_id TEXT PRIMARY KEY,
    chat_id TEXT,
    message_id TEXT,
    tool TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_files_json TEXT NOT NULL DEFAULT '[]',
    affected_files_json TEXT NOT NULL DEFAULT '[]',
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_runs_started ON tool_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS audio_analysis_cache (
    cache_key TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    analysis_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_type(extension: str, mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "images"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("text/") or extension in {".pdf", ".doc", ".docx", ".md", ".rtf"}:
        return "documents"
    return "other"


class FileRegistry:
    """Small SQLite-backed registry; it never scans the user's filesystem."""

    def __init__(self, database_path: str | os.PathLike[str]):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "FileRegistry":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def register(
        self,
        path: str | os.PathLike[str],
        *,
        source_type: str = "uploaded",
        created_by: str = "user",
        managed_path: str | os.PathLike[str] | None = None,
        metadata: dict[str, Any] | None = None,
        calculate_hash: bool = False,
    ) -> int:
        file_path = Path(path)
        stat = file_path.stat()
        filename = file_path.name
        extension = file_path.suffix.lower()
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        now = _now()
        digest = None
        if calculate_hash:
            digest_hash = hashlib.sha256()
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest_hash.update(chunk)
            digest = digest_hash.hexdigest()
        cursor = self._connection.execute(
            """
            INSERT INTO files (
                filename, extension, mime_type, file_type, size_bytes,
                managed_path, original_path, source_type, created_by,
                created_at, updated_at, is_generated, is_uploaded,
                is_missing, optional_hash, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                filename,
                extension,
                mime_type,
                _file_type(extension, mime_type),
                stat.st_size,
                str(managed_path) if managed_path else None,
                str(file_path),
                source_type,
                created_by,
                now,
                now,
                int(source_type in {"generated", "exported"}),
                int(source_type in {"uploaded", "attached", "shared"}),
                digest,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def link(
        self,
        file_id: int,
        chat_id: str,
        *,
        message_id: str | None = None,
        relationship_type: str = "attached",
    ) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO file_chat_links
                (file_id, chat_id, message_id, linked_at, relationship_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, chat_id, message_id, _now(), relationship_type),
        )
        self._connection.commit()

    def search(
        self,
        query: str = "",
        *,
        file_type: str | None = None,
        source_type: str | None = None,
        sort: str = "newest",
    ) -> list[dict[str, Any]]:
        order = {
            "newest": "f.updated_at DESC",
            "oldest": "f.updated_at ASC",
            "filename": "LOWER(f.filename) ASC",
            "type": "f.file_type ASC, LOWER(f.filename) ASC",
            "size": "f.size_bytes DESC",
        }.get(sort)
        if not order:
            raise ValueError(f"Unsupported sort: {sort}")
        clauses: list[str] = []
        values: list[Any] = []
        if query:
            pattern = f"%{query}%"
            clauses.append(
                "(f.filename LIKE ? OR f.extension LIKE ? OR f.mime_type LIKE ? "
                "OR f.file_type LIKE ? OR f.source_type LIKE ?)"
            )
            values.extend([pattern] * 5)
        if file_type:
            clauses.append("f.file_type = ?")
            values.append(file_type)
        if source_type:
            clauses.append("f.source_type = ?")
            values.append(source_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"""
            SELECT f.*, GROUP_CONCAT(
                l.chat_id || COALESCE(':' || l.message_id, ''), '||'
            ) AS chat_links
            FROM files f
            LEFT JOIN file_chat_links l ON l.file_id = f.id
            {where}
            GROUP BY f.id
            ORDER BY {order}
            """,
            values,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            item["is_generated"] = bool(item["is_generated"])
            item["is_uploaded"] = bool(item["is_uploaded"])
            item["is_missing"] = bool(item["is_missing"])
            item["chat_links"] = item.pop("chat_links").split("||") if item["chat_links"] else []
            result.append(item)
        return result

    def refresh_missing(self) -> int:
        rows = self._connection.execute("SELECT id, original_path, managed_path FROM files").fetchall()
        missing = 0
        for row in rows:
            paths = [row["original_path"], row["managed_path"]]
            is_missing = not any(path and Path(path).is_file() for path in paths)
            missing += int(is_missing)
            self._connection.execute(
                "UPDATE files SET is_missing = ?, updated_at = ? WHERE id = ?",
                (int(is_missing), _now(), row["id"]),
            )
        self._connection.commit()
        return missing

    def delete_record(self, file_id: int) -> None:
        self._connection.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self._connection.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the scoped connection to the local tool subsystem.

        The connection remains owned by this registry; callers must not close
        it.  Keeping one connection also makes tool runs and index updates
        transactional with File Manager registration.
        """
        return self._connection

    def register_generated(
        self,
        path: str | os.PathLike[str],
        *,
        chat_id: str | None = None,
        message_id: str | None = None,
        tool_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        file_id = self.register(
            path,
            source_type="generated",
            created_by="local-agent",
            managed_path=path,
            metadata=metadata,
            calculate_hash=True,
        )
        if chat_id:
            self.link(file_id, chat_id, message_id=message_id, relationship_type="generated")
        if tool_run_id:
            row = self._connection.execute(
                "SELECT created_files_json FROM tool_runs WHERE tool_run_id = ?", (tool_run_id,)
            ).fetchone()
            if row:
                created = json.loads(row["created_files_json"] or "[]")
                created.append(str(path))
                self._connection.execute(
                    "UPDATE tool_runs SET created_files_json = ? WHERE tool_run_id = ?",
                    (json.dumps(created), tool_run_id),
                )
            self._connection.commit()
        return file_id

    def upsert_indexed(
        self,
        path: str | os.PathLike[str],
        *,
        content_text: str = "",
        optional_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        is_missing: bool = False,
    ) -> None:
        file_path = Path(path)
        normalized = str(file_path.resolve())
        now = _now()
        if file_path.exists() and file_path.is_file():
            stat = file_path.stat()
            filename = file_path.name
            extension = file_path.suffix.lower()
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            values = (
                normalized, filename, extension, mime_type, _file_type(extension, mime_type),
                stat.st_size, datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(timespec="seconds"),
                datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                now, content_text, optional_hash, json.dumps(metadata or {}, ensure_ascii=False),
                int(is_missing),
            )
        else:
            existing = self._connection.execute(
                "SELECT filename, extension, mime_type, file_type, size_bytes, created_at, "
                "modified_at, content_text, optional_hash, metadata_json FROM indexed_files WHERE path = ?",
                (normalized,),
            ).fetchone()
            if not existing:
                return
            values = (
                normalized, existing["filename"], existing["extension"], existing["mime_type"],
                existing["file_type"], existing["size_bytes"], existing["created_at"],
                existing["modified_at"], now, existing["content_text"], existing["optional_hash"],
                existing["metadata_json"], 1,
            )
        self._connection.execute(
            """
            INSERT INTO indexed_files
                (path, filename, extension, mime_type, file_type, size_bytes, created_at,
                 modified_at, indexed_at, content_text, optional_hash, metadata_json, is_missing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename, extension=excluded.extension,
                mime_type=excluded.mime_type, file_type=excluded.file_type,
                size_bytes=excluded.size_bytes, created_at=excluded.created_at,
                modified_at=excluded.modified_at, indexed_at=excluded.indexed_at,
                content_text=excluded.content_text, optional_hash=excluded.optional_hash,
                metadata_json=excluded.metadata_json, is_missing=excluded.is_missing
            """,
            values,
        )

    def search_index(
        self,
        query: str = "",
        *,
        extension: str | None = None,
        directory: str | os.PathLike[str] | None = None,
        file_type: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        include_missing: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if query:
            pattern = f"%{query}%"
            clauses.append("(filename LIKE ? OR path LIKE ? OR content_text LIKE ? OR metadata_json LIKE ?)")
            values.extend([pattern] * 4)
        if extension:
            clauses.append("extension = ?")
            values.append(extension.lower() if extension.startswith(".") else f".{extension.lower()}")
        if directory:
            directory_path = str(Path(directory).resolve())
            clauses.append("(path = ? OR path LIKE ?)")
            values.extend([directory_path, directory_path.rstrip("\\/") + os.sep + "%"])
        if file_type:
            clauses.append("file_type = ?")
            values.append(file_type)
        if min_size is not None:
            clauses.append("size_bytes >= ?")
            values.append(int(min_size))
        if max_size is not None:
            clauses.append("size_bytes <= ?")
            values.append(int(max_size))
        if not include_missing:
            clauses.append("is_missing = 0")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM indexed_files{where} ORDER BY CASE WHEN LOWER(filename) LIKE LOWER(?) "
            f"THEN 0 ELSE 1 END, modified_at DESC LIMIT ?",
            [*values, f"%{query}%", max(1, min(int(limit), 10000))],
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            item["is_missing"] = bool(item["is_missing"])
            result.append(item)
        return result

    def log_operation(self, operation_id: str, operation_type: str, *, source: str | None = None,
                      destination: str | None = None, status: str = "completed",
                      tool_run_id: str | None = None, chat_id: str | None = None,
                      metadata: dict[str, Any] | None = None) -> None:
        self._connection.execute(
            "INSERT INTO file_operations(operation_id, operation_type, source, destination, "
            "timestamp, status, tool_run_id, chat_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (operation_id, operation_type, source, destination, _now(), status, tool_run_id,
             chat_id, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        self._connection.commit()

    def operations(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM file_operations ORDER BY timestamp DESC LIMIT ?", (max(1, min(limit, 1000)),)
        ).fetchall()
        return [dict(row) for row in rows]
