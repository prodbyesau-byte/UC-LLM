"""Local HTTP bridge for the Milestone 1 file registry.

The server binds to loopback only. It accepts explicit uploads and never scans
the user's filesystem.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from file_registry import FileRegistry
from local_tools import TOOL_NAMES, ToolRouter


ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
LIBRARY = ROOT / "runtime" / "file-library"
DATABASE = ROOT / "runtime" / "files.sqlite"
GENERATED = ROOT / CONFIG.get("FILES_GENERATED_DIRECTORY", "runtime/file-library/generated")


def response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8000")
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8000")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            with ToolRouter(DATABASE) as tools:
                response(self, 200, {"status": "ok", "tool_router": True,
                                     "indexed_files": tools.registry.connection.execute(
                                         "SELECT COUNT(*) FROM indexed_files").fetchone()[0]})
            return
        if parsed.path == "/tools":
            response(self, 200, {"tools": list(TOOL_NAMES)})
            return
        if parsed.path == "/operations":
            query = parse_qs(parsed.query)
            with FileRegistry(DATABASE) as registry:
                response(self, 200, {"operations": registry.operations(int(query.get("limit", ["100"])[0]))})
            return
        if parsed.path != "/files":
            response(self, 404, {"error": "not found"})
            return
        query = parse_qs(parsed.query)
        with FileRegistry(DATABASE) as registry:
            registry.refresh_missing()
            files = registry.search(
                query.get("q", [""])[0],
                file_type=query.get("type", [None])[0],
                source_type=query.get("source", [None])[0],
                sort=query.get("sort", ["newest"])[0],
            )
            indexed = registry.search_index(query.get("q", [""])[0],
                                           extension=query.get("extension", [None])[0],
                                           file_type=query.get("type", [None])[0],
                                           include_missing=True)
            known = {item.get("original_path") or item.get("managed_path") for item in files}
            for item in indexed:
                if item["path"] not in known:
                    item.update({"id": "indexed:" + item["path"], "original_path": item["path"],
                                 "managed_path": item["path"], "source_type": "indexed",
                                 "is_generated": False, "is_uploaded": False})
                    files.append(item)
        response(self, 200, {"files": files})

    def do_POST(self) -> None:
        parsed_path = urlparse(self.path).path
        if parsed_path in {"/tools/run", "/index/refresh"}:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * 1024 * 1024:
                response(self, 400, {"error": "JSON request is empty or too large"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                response(self, 400, {"error": f"invalid JSON: {exc}"})
                return
            if parsed_path == "/index/refresh":
                body = {"tool": "FILE_SEARCH", "arguments": {
                    "roots": body.get("roots", []), "max_files": body.get("max_files")}}
            if not isinstance(body, dict) or not body.get("tool"):
                response(self, 400, {"error": "tool is required"})
                return
            with ToolRouter(DATABASE, generated_root=GENERATED) as tools:
                result = tools.run(
                    body["tool"], body.get("arguments", {}),
                    chat_id=self.headers.get("X-Chat-Id"),
                    message_id=self.headers.get("X-Message-Id"),
                    approved=bool(body.get("approved")),
                )
            response(self, 200 if result["status"] != "failed" else 400, result)
            return
        if parsed_path != "/files":
            response(self, 404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 100 * 1024 * 1024:
            response(self, 413, {"error": "file is empty or exceeds 100 MB"})
            return
        filename = Path(self.headers.get("X-File-Name", "upload.bin")).name
        content = self.rfile.read(length)
        LIBRARY.mkdir(parents=True, exist_ok=True)
        destination = LIBRARY / f"{uuid.uuid4().hex[:12]}-{filename}"
        destination.write_bytes(content)
        source_type = self.headers.get("X-Source-Type", "uploaded")
        with FileRegistry(DATABASE) as registry:
            file_id = registry.register(
                destination,
                source_type=source_type,
                created_by="user",
                managed_path=destination,
                metadata={"original_filename": filename},
                calculate_hash=True,
            )
            chat_id = self.headers.get("X-Chat-Id")
            if chat_id:
                registry.link(file_id, chat_id, message_id=self.headers.get("X-Message-Id"))
            item = registry.search(query=filename)[0]
        response(self, 201, item)


if __name__ == "__main__":
    port = int(os.environ.get("FILES_PORT", CONFIG.get("FILES_PORT", 8090)))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
