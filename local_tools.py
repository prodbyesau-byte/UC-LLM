"""Safe, local-only Milestone One tools.

The module deliberately exposes deterministic operations instead of a shell
escape hatch.  ``ToolRouter`` is the single entry point used by the HTTP
bridge and can also be used directly by the desktop application.
"""

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import sqlite3
import struct
import threading
import tempfile
import time
import uuid
import wave
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from file_registry import FileRegistry

try:  # Optional: XLSX support is enabled when the existing environment has it.
    import openpyxl
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font
except ImportError:  # pragma: no cover - exercised in minimal deployments
    openpyxl = None


ANALYSIS_VERSION = "audio-1"
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".log"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | {".docx", ".pdf", ".xlsx"}
TOOL_NAMES = (
    "CHAT", "WEB_SEARCH", "FILE_SEARCH", "FILE_INSPECT", "FILE_COPY",
    "FILE_MOVE", "FILE_RENAME", "FILE_DELETE", "FILE_ORGANIZE", "FOLDER_CREATE",
    "DISK_ANALYSIS", "DUPLICATE_SEARCH", "DOCUMENT_CREATE", "DOCUMENT_READ",
    "DOCUMENT_CONVERT", "PDF_CREATE", "PDF_READ", "SPREADSHEET_CREATE",
    "SPREADSHEET_READ", "AUDIO_METADATA", "AUDIO_ANALYZE", "AUDIO_COMPARE",
    "SYSTEM_INFO", "MULTI_TOOL_TASK", "FILE_UNDO",
)


class PermissionLevel(str, Enum):
    READ_ONLY = "A"
    NON_DESTRUCTIVE_WRITE = "B"
    DESTRUCTIVE = "C"


class ToolError(ValueError):
    """A user-actionable validation or execution error."""


@dataclass
class ToolResult:
    tool: str
    status: str
    result: Any = None
    errors: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    tool_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool, "status": self.status, "result": self.result,
            "errors": self.errors, "affected_files": self.affected_files,
            "created_files": self.created_files, "metadata": self.metadata,
            "duration": round(self.duration, 4), "tool_run_id": self.tool_run_id,
        }


class PermissionManager:
    """Centralized action policy shared by every file-writing route."""

    READ_TOOLS = {
        "FILE_SEARCH", "FILE_INSPECT", "DISK_ANALYSIS", "DUPLICATE_SEARCH",
        "DOCUMENT_READ", "PDF_READ", "SPREADSHEET_READ", "AUDIO_METADATA",
        "AUDIO_ANALYZE", "AUDIO_COMPARE", "SYSTEM_INFO",
    }
    WRITE_TOOLS = {
        "FILE_COPY", "FOLDER_CREATE", "DOCUMENT_CREATE", "DOCUMENT_CONVERT",
        "PDF_CREATE", "SPREADSHEET_CREATE",
    }
    DESTRUCTIVE_TOOLS = {
        "FILE_MOVE", "FILE_RENAME", "FILE_DELETE", "FILE_ORGANIZE", "FILE_UNDO",
    }

    def level(self, tool: str) -> PermissionLevel:
        if tool in self.READ_TOOLS:
            return PermissionLevel.READ_ONLY
        if tool in self.WRITE_TOOLS:
            return PermissionLevel.NON_DESTRUCTIVE_WRITE
        if tool in self.DESTRUCTIVE_TOOLS:
            return PermissionLevel.DESTRUCTIVE
        return PermissionLevel.READ_ONLY

    def authorize(self, tool: str, *, approved: bool = False, permanent: bool = False) -> None:
        level = self.level(tool)
        # Organization has a safe preview phase; executing the returned plan
        # still requires approval in ``_organize``.
        if level is PermissionLevel.DESTRUCTIVE and tool != "FILE_ORGANIZE" and not approved:
            raise ToolError("approval_required: this operation may change or delete files")
        if tool == "FILE_DELETE" and permanent and not approved:
            raise ToolError("approval_required: permanent deletion requires explicit approval")


class PathPolicy:
    """Canonical path and protected-directory checks."""

    PROTECTED_NAMES = {
        "windows", "system32", "program files", "program files (x86)",
        "programdata", "boot", "recovery",
    }

    def __init__(self, allowed_roots: Iterable[str | os.PathLike[str]] | None = None):
        self.allowed_roots = [Path(p).expanduser().resolve() for p in (allowed_roots or [])]

    def canonical(self, value: str | os.PathLike[str]) -> Path:
        if not value or "\x00" in str(value):
            raise ToolError("invalid_path")
        path = Path(value).expanduser()
        try:
            return path.resolve(strict=False)
        except OSError as exc:
            raise ToolError(f"invalid_path: {exc}") from exc

    def validate(self, value: str | os.PathLike[str], *, must_exist: bool = False,
                 directory: bool | None = None, allow_protected: bool = False) -> Path:
        path = self.canonical(value)
        if self.allowed_roots and not any(path == root or root in path.parents for root in self.allowed_roots):
            raise ToolError("path_outside_allowed_roots")
        names = {part.casefold() for part in path.parts}
        if not allow_protected and names & self.PROTECTED_NAMES:
            raise ToolError("protected_directory")
        if must_exist and not path.exists():
            raise ToolError("file_not_found")
        if directory is True and path.exists() and not path.is_dir():
            raise ToolError("directory_required")
        if directory is False and path.exists() and not path.is_file():
            raise ToolError("file_required")
        return path

    def ensure_destination(self, value: str | os.PathLike[str], *, overwrite: bool = False) -> Path:
        path = self.validate(value, allow_protected=False)
        if path.exists() and not overwrite:
            raise ToolError("destination_exists: approval is required to overwrite")
        return path


def _sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_name(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError("unable_to_choose_safe_destination")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentEngine:
    """Small local reader/writer for the formats needed by the file agent."""

    def read(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".markdown", ".log", ".json"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"path": str(path), "format": suffix[1:], "text": text,
                    "characters": len(text), "headings": self._headings(text)}
        if suffix == ".csv":
            with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
                rows = list(csv.reader(handle))
            return {"path": str(path), "format": "csv", "rows": rows,
                    "headers": rows[0] if rows else [], "row_count": len(rows)}
        if suffix == ".docx":
            return self._read_docx(path)
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix == ".xlsx":
            return SpreadsheetEngine().read(path)
        raise ToolError(f"unsupported_document_format: {suffix or 'unknown'}")

    @staticmethod
    def _headings(text: str) -> list[str]:
        return [line.lstrip("# ").strip() for line in text.splitlines()
                if line.startswith("#")][:100]

    def create(self, destination: Path, content: Any, *, title: str | None = None) -> Path:
        suffix = destination.suffix.lower()
        if suffix == ".docx":
            return self._create_docx(destination, content, title)
        if suffix == ".pdf":
            return self._create_pdf(destination, content, title)
        if suffix in {".txt", ".md"}:
            destination.write_text(str(content), encoding="utf-8")
            return destination
        if suffix == ".csv":
            rows = content if isinstance(content, list) else [content]
            with destination.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(rows)
            return destination
        raise ToolError(f"unsupported_document_format: {suffix or 'unknown'}")

    @staticmethod
    def _content_lines(content: Any, title: str | None) -> list[str]:
        lines: list[str] = []
        if title:
            lines.append(title)
        if isinstance(content, str):
            lines.extend(content.splitlines() or [""])
        elif isinstance(content, dict):
            for key, value in content.items():
                lines.append(str(key))
                lines.extend(str(value).splitlines())
        elif isinstance(content, list):
            for item in content:
                lines.append("• " + " ".join(map(str, item)) if isinstance(item, (list, tuple))
                             else str(item))
        else:
            lines.append(str(content))
        return lines

    def _create_docx(self, destination: Path, content: Any, title: str | None) -> Path:
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        document = ET.Element(f"{{{ns}}}document")
        body = ET.SubElement(document, f"{{{ns}}}body")
        lines = self._content_lines(content, title)
        for index, line in enumerate(lines):
            paragraph = ET.SubElement(body, f"{{{ns}}}p")
            if index == 0 and title:
                properties = ET.SubElement(paragraph, f"{{{ns}}}pPr")
                ET.SubElement(properties, f"{{{ns}}}pStyle", {f"{{{ns}}}val": "Title"})
            run = ET.SubElement(paragraph, f"{{{ns}}}r")
            ET.SubElement(run, f"{{{ns}}}t").text = line
        ET.SubElement(body, f"{{{ns}}}sectPr")
        content_types = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
        rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels)
            archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        return destination

    def _read_docx(self, path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(path) as archive:
            xml = ET.fromstring(archive.read("word/document.xml"))
        texts = [node.text or "" for node in xml.iter()
                 if node.tag.rsplit("}", 1)[-1] == "t"]
        paragraphs = "\n".join(texts)
        return {"path": str(path), "format": "docx", "text": paragraphs,
                "paragraphs": paragraphs.splitlines(), "headings": []}

    def _create_pdf(self, destination: Path, content: Any, title: str | None) -> Path:
        # A dependency-free, standards-compliant text PDF.  It intentionally
        # does not execute or embed arbitrary document content.
        lines = self._content_lines(content, title)
        pages = [lines[i:i + 48] for i in range(0, max(1, len(lines)), 48)]
        objects: list[bytes] = []
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        page_ids = []
        for page in pages:
            page_ids.append(3 + len(page_ids) * 2)
        kids = " ".join(f"{pid} 0 R" for pid in page_ids).encode()
        objects.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode() + b" >>")
        for page in pages:
            page_id = 3 + len(page_ids) * 2  # placeholder, fixed below
            stream_lines = ["BT", "/F1 11 Tf", "50 760 Td"]
            for line in page:
                escaped = str(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream_lines.append(f"({escaped[:110]}) Tj 0 -15 Td")
            stream_lines.append("ET")
            stream = "\n".join(stream_lines).encode("latin-1", "replace")
            page_id = len(objects) + 1
            content_id = page_id + 1
            objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                          b"/Resources << /Font << /F1 0 0 R >> >> /Contents " +
                          str(content_id).encode() + b" 0 R >>")
            objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        # Page resources above point to the final font object.
        font_id = len(objects)
        for index, obj in enumerate(objects):
            if b"/Type /Page" in obj:
                objects[index] = re.sub(rb"/F1 \d+ 0 R", f"/F1 {font_id} 0 R".encode(), obj)
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
        startxref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
        output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
        output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode())
        destination.write_bytes(output)
        return destination

    def _read_pdf(self, path: Path) -> dict[str, Any]:
        data = path.read_bytes()
        text = "\n".join(x.decode("latin-1", "replace")
                         for x in re.findall(rb"\(([^()]*)\)\s*Tj", data))
        return {"path": str(path), "format": "pdf", "text": text,
                "characters": len(text), "pages": data.count(b"/Type /Page")}

    def convert(self, source: Path, destination: Path) -> Path:
        data = self.read(source)
        content = data.get("text") if "text" in data else data.get("rows", [])
        if destination.suffix.lower() == ".xlsx":
            return SpreadsheetEngine().create(destination, {"Sheet1": content}, title=source.stem)
        return self.create(destination, content, title=source.stem)


class SpreadsheetEngine:
    def create(self, destination: Path, sheets: dict[str, Any], *, title: str | None = None,
               chart: bool = False) -> Path:
        if openpyxl is None:
            raise ToolError("xlsx_dependency_unavailable: install openpyxl locally")
        workbook = openpyxl.Workbook()
        first = True
        for name, rows in (sheets.items() if isinstance(sheets, dict) else {"Sheet1": sheets}.items()):
            sheet = workbook.active if first else workbook.create_sheet()
            first = False
            sheet.title = str(name)[:31] or "Sheet"
            for row_index, row in enumerate(rows if isinstance(rows, list) else [[rows]], 1):
                values = row if isinstance(row, (list, tuple)) else [row]
                for column_index, value in enumerate(values, 1):
                    sheet.cell(row_index, column_index, value)
            if sheet.max_row and sheet.max_column:
                sheet.freeze_panes = "A2"
                sheet.auto_filter.ref = sheet.dimensions
                for cell in sheet[1]:
                    cell.font = Font(bold=True)
                for column in sheet.columns:
                    letter = column[0].column_letter
                    width = min(50, max(10, max(len(str(cell.value or "")) for cell in column) + 2))
                    sheet.column_dimensions[letter].width = width
                if chart and sheet.max_row >= 2 and sheet.max_column >= 2:
                    chart_obj = BarChart()
                    chart_obj.title = f"{sheet.title} overview"
                    chart_obj.add_data(Reference(sheet, min_col=2, min_row=1,
                                                 max_row=sheet.max_row), titles_from_data=True)
                    chart_obj.set_categories(Reference(sheet, min_col=1, min_row=2,
                                                        max_row=sheet.max_row))
                    sheet.add_chart(chart_obj, f"A{sheet.max_row + 3}")
        if title:
            workbook.properties.title = title
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(destination)
        return destination

    def read(self, path: Path) -> dict[str, Any]:
        if openpyxl is None:
            raise ToolError("xlsx_dependency_unavailable: install openpyxl locally")
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=True)
        sheets: dict[str, Any] = {}
        try:
            for sheet in workbook.worksheets:
                sheets[sheet.title] = [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
        return {"path": str(path), "format": "xlsx", "sheet_names": list(sheets),
                "sheets": sheets}


class AudioEngine:
    """Deterministic WAV analysis with optional mutagen metadata support."""

    def __init__(self, registry: FileRegistry):
        self.registry = registry

    def metadata(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        if suffix == ".wav":
            try:
                with wave.open(str(path), "rb") as audio:
                    return {
                        "path": str(path), "format": "WAV",
                        "duration_seconds": round(audio.getnframes() / audio.getframerate(), 6),
                        "sample_rate": audio.getframerate(), "channels": audio.getnchannels(),
                        "bit_depth": audio.getsampwidth() * 8, "frames": audio.getnframes(),
                        "file_size": path.stat().st_size,
                    }
            except (wave.Error, EOFError) as exc:
                raise ToolError(f"unsupported_or_corrupt_audio: {exc}") from exc
        try:
            from mutagen import File as MutagenFile  # type: ignore
            audio = MutagenFile(path)
            if audio is None or not audio.info:
                raise ToolError("unsupported_or_corrupt_audio")
            info = audio.info
            return {"path": str(path), "format": suffix.lstrip(".").upper(),
                    "duration_seconds": getattr(info, "length", None),
                    "sample_rate": getattr(info, "sample_rate", None),
                    "channels": getattr(info, "channels", None),
                    "bitrate": getattr(info, "bitrate", None), "file_size": path.stat().st_size}
        except ImportError as exc:
            raise ToolError("audio_decoder_unavailable: WAV is supported without optional dependencies") from exc

    def analyze(self, path: Path) -> dict[str, Any]:
        metadata = self.metadata(path)
        if metadata["format"] != "WAV":
            raise ToolError("audio_analysis_requires_wav_or_decoder")
        stat = path.stat()
        cache_key = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{ANALYSIS_VERSION}"
        row = self.registry.connection.execute(
            "SELECT result_json FROM audio_analysis_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row:
            result = json.loads(row["result_json"])
            result["cache_hit"] = True
            return result
        with wave.open(str(path), "rb") as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
            raw = audio.readframes(frames)
        samples = self._samples(raw, width)
        if not samples:
            raise ToolError("audio_has_no_samples")
        per_channel = [samples[i::channels] for i in range(channels)]
        values = [value for channel in per_channel for value in channel]
        peak = max(abs(value) for value in values) / float(1 << (width * 8 - 1))
        rms = (sum(value * value for value in values) / len(values)) ** 0.5 / float(1 << (width * 8 - 1))
        loudness = 20 * _safe_log10(rms) - 0.691  # BS.1770-style calibrated estimate.
        left = per_channel[0]
        right = per_channel[1] if channels > 1 else left
        correlation = self._correlation(left, right)
        result = {
            **metadata, "cache_hit": False, "integrated_loudness_lufs": round(loudness, 3),
            "rms": round(rms, 8), "sample_peak": round(peak, 8),
            "true_peak_db": None, "true_peak_note": "not measured; sample peak only",
            "crest_factor_db": round(20 * _safe_log10(peak / max(rms, 1e-12)), 3),
            "clipping_samples": sum(1 for value in values if abs(value) >= (1 << (width * 8 - 1)) - 1),
            "stereo": {"left_rms": round(self._rms(left) / (1 << (width * 8 - 1)), 8),
                       "right_rms": round(self._rms(right) / (1 << (width * 8 - 1)), 8),
                       "correlation": round(correlation, 6), "mono": channels == 1},
            "spectrum": self._spectrum(values, width, rate),
            "waveform": {"samples": [
                round(value / float(1 << (width * 8 - 1)), 6)
                for value in values[::max(1, len(values) // 256)][:256]
            ]},
            "loudness_over_time": [],
            "analysis_version": ANALYSIS_VERSION,
        }
        self.registry.connection.execute(
            "INSERT OR REPLACE INTO audio_analysis_cache(cache_key, path, size_bytes, modified_ns, "
            "analysis_version, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cache_key, str(path), stat.st_size, stat.st_mtime_ns, ANALYSIS_VERSION,
             json.dumps(result), _now()),
        )
        self.registry.connection.commit()
        return result

    @staticmethod
    def _samples(raw: bytes, width: int) -> list[int]:
        if width == 1:
            return [value - 128 for value in raw]
        if width == 2:
            return list(struct.unpack("<" + "h" * (len(raw) // 2), raw))
        if width == 3:
            return [int.from_bytes(raw[index:index + 3], "little", signed=True)
                    for index in range(0, len(raw) - 2, 3)]
        if width == 4:
            return list(struct.unpack("<" + "i" * (len(raw) // 4), raw))
        raise ToolError(f"unsupported_wav_bit_depth: {width * 8}")

    @staticmethod
    def _rms(values: list[int]) -> float:
        return (sum(value * value for value in values) / max(1, len(values))) ** 0.5

    @staticmethod
    def _correlation(left: list[int], right: list[int]) -> float:
        count = min(len(left), len(right))
        if not count:
            return 0.0
        left, right = left[:count], right[:count]
        lm, rm = sum(left) / count, sum(right) / count
        numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
        denominator = (sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right)) ** 0.5
        return numerator / denominator if denominator else 1.0

    @staticmethod
    def _spectrum(values: list[int], width: int, rate: int) -> dict[str, Any]:
        # Band energy is deterministic and bounded; use at most 4096 samples.
        values = values[:4096]
        limit = float(1 << (width * 8 - 1))
        bands = {"low": (20, 250), "low_mid": (250, 500), "mid": (500, 2000),
                 "upper_mid": (2000, 6000), "high": (6000, max(6001, rate // 2))}
        energy: dict[str, float] = {}
        for name, (low, high) in bands.items():
            energy[name] = round(sum(abs(value / limit) for value in values) / max(1, len(values))
                                 * (high - low), 6)
        return {"bands": energy, "sample_window": len(values)}

    def compare(self, first: Path, second: Path) -> dict[str, Any]:
        left, right = self.analyze(first), self.analyze(second)
        keys = ("integrated_loudness_lufs", "sample_peak", "rms", "crest_factor_db")
        differences = {key: round(right[key] - left[key], 6) for key in keys}
        differences["stereo_correlation"] = round(
            right["stereo"]["correlation"] - left["stereo"]["correlation"], 6)
        return {"first": left, "second": right, "differences": differences}


def _safe_log10(value: float) -> float:
    import math
    return math.log10(max(value, 1e-12))


class FileIndexer:
    def __init__(self, registry: FileRegistry, policy: PathPolicy | None = None):
        self.registry, self.policy = registry, policy or PathPolicy()

    def refresh_async(self, roots: Iterable[str | os.PathLike[str]], *,
                      cancel_event: Any = None, callback: Any = None,
                      max_files: int | None = None,
                      exclusions: Iterable[str] = ()) -> threading.Thread:
        """Run a refresh off the UI thread; ``cancel_event`` is cooperative."""
        def worker() -> None:
            result = self.refresh(roots, cancel_event=cancel_event, max_files=max_files,
                                  exclusions=exclusions)
            if callback:
                callback(result)
        thread = threading.Thread(target=worker, name="local-ai-file-index", daemon=True)
        thread.start()
        return thread

    def refresh(self, roots: Iterable[str | os.PathLike[str]], *, cancel_event: Any = None,
                max_files: int | None = None, exclusions: Iterable[str] = ()) -> dict[str, int]:
        root_paths = [self.policy.validate(root, must_exist=True, directory=True) for root in roots]
        excluded = {str(Path(item).resolve()) for item in exclusions}
        seen: set[str] = set()
        scanned = changed = 0
        for root in root_paths:
            for current, dirs, files in os.walk(root):
                if cancel_event and cancel_event.is_set():
                    return {"scanned": scanned, "changed": changed, "cancelled": 1}
                current_path = Path(current)
                dirs[:] = [item for item in dirs if str((current_path / item).resolve()) not in excluded
                           and item not in {".git", "__pycache__"}]
                for name in files:
                    if max_files is not None and scanned >= max_files:
                        break
                    path = current_path / name
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    normalized = str(path.resolve())
                    seen.add(normalized)
                    previous = self.registry.connection.execute(
                        "SELECT size_bytes, modified_at FROM indexed_files WHERE path = ?", (normalized,)
                    ).fetchone()
                    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
                    if previous and previous["size_bytes"] == stat.st_size and previous["modified_at"] == modified:
                        scanned += 1
                        continue
                    content = ""
                    if path.suffix.lower() in DOCUMENT_EXTENSIONS and stat.st_size <= 2 * 1024 * 1024:
                        try:
                            data = DocumentEngine().read(path)
                            content = data.get("text", "")
                            if not content and "rows" in data:
                                content = "\n".join(",".join(map(str, row)) for row in data["rows"])
                            if not content and "sheets" in data:
                                content = "\n".join(
                                    ",".join(map(str, row))
                                    for rows in data["sheets"].values() for row in rows
                                )
                        except (OSError, ToolError, zipfile.BadZipFile):
                            content = ""
                    digest = _sha256(path) if stat.st_size <= 16 * 1024 * 1024 else None
                    self.registry.upsert_indexed(path, content_text=content, optional_hash=digest)
                    scanned += 1
                    changed += 1
                if max_files is not None and scanned >= max_files:
                    break
        missing = 0
        for row in self.registry.connection.execute("SELECT path FROM indexed_files").fetchall():
            path = row["path"]
            if any(path == str(root) or path.startswith(str(root).rstrip("\\/") + os.sep)
                   for root in root_paths) and path not in seen:
                self.registry.upsert_indexed(path, is_missing=True)
                missing += 1
        self.registry.connection.commit()
        return {"scanned": scanned, "changed": changed, "missing": missing, "cancelled": 0}


class ToolRouter:
    """Structured dispatcher, persistence boundary, and verification layer."""

    def __init__(self, database_path: str | os.PathLike[str], *,
                 allowed_roots: Iterable[str | os.PathLike[str]] | None = None,
                 generated_root: str | os.PathLike[str] | None = None):
        self.registry = FileRegistry(database_path)
        self.policy = PathPolicy(allowed_roots)
        self.permissions = PermissionManager()
        self.indexer = FileIndexer(self.registry, self.policy)
        self.documents, self.spreadsheets = DocumentEngine(), SpreadsheetEngine()
        self.audio = AudioEngine(self.registry)
        self.generated_root = Path(generated_root or Path(database_path).parent / "generated").resolve()

    def close(self) -> None:
        self.registry.close()

    def __enter__(self) -> "ToolRouter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run(self, tool: str, arguments: dict[str, Any] | None = None, *,
            chat_id: str | None = None, message_id: str | None = None,
            approved: bool = False) -> dict[str, Any]:
        tool = str(tool).upper()
        if tool not in TOOL_NAMES:
            return ToolResult(tool, "failed", errors=[f"unknown_tool: {tool}"]).to_dict()
        arguments = dict(arguments or {})
        if approved:
            arguments["approved"] = True
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        started_at = _now()
        self.registry.connection.execute(
            "INSERT INTO tool_runs(tool_run_id, chat_id, message_id, tool, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)", (run_id, chat_id, message_id, tool, started_at, "running"))
        self.registry.connection.commit()
        try:
            self.permissions.authorize(tool, approved=approved, permanent=bool(arguments.get("permanent")))
            result = self._dispatch(tool, arguments, run_id, chat_id)
            result.tool_run_id = run_id
        except (ToolError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, zipfile.BadZipFile) as exc:
            result = ToolResult(tool, "failed", errors=[str(exc)], tool_run_id=run_id)
        result.duration = time.monotonic() - started
        self.registry.connection.execute(
            "UPDATE tool_runs SET completed_at = ?, status = ?, summary = ?, created_files_json = ?, "
            "affected_files_json = ?, error = ? WHERE tool_run_id = ?",
            (_now(), result.status, str(result.result)[:500],
             json.dumps(result.created_files), json.dumps(result.affected_files),
             "; ".join(result.errors) if result.errors else None, run_id))
        self.registry.connection.commit()
        return result.to_dict()

    def _path(self, arguments: dict[str, Any], key: str = "path", **kwargs: Any) -> Path:
        return self.policy.validate(arguments.get(key), **kwargs)

    def _dispatch(self, tool: str, args: dict[str, Any], run_id: str,
                  chat_id: str | None) -> ToolResult:
        if tool == "FILE_SEARCH" and args.get("roots"):
            refreshed = self.indexer.refresh(args["roots"], cancel_event=args.get("cancel_event"),
                                             max_files=args.get("max_files"), exclusions=args.get("exclusions", []))
            result = self.registry.search_index(args.get("query", ""), extension=args.get("extension"),
                directory=args.get("directory"), file_type=args.get("file_type"),
                min_size=args.get("min_size"), max_size=args.get("max_size"),
                include_missing=bool(args.get("include_missing")), limit=args.get("limit", 100))
            return ToolResult(tool, "completed", result={"refresh": refreshed, "files": result})
        if tool == "FILE_SEARCH":
            result = self.registry.search_index(args.get("query", ""), extension=args.get("extension"),
                directory=args.get("directory"), file_type=args.get("file_type"),
                min_size=args.get("min_size"), max_size=args.get("max_size"),
                include_missing=bool(args.get("include_missing")), limit=args.get("limit", 100))
            return ToolResult(tool, "completed", result=result)
        if tool == "FILE_INSPECT":
            path = self._path(args, must_exist=True, directory=False)
            stat = path.stat()
            result = {"path": str(path), "name": path.name, "size_bytes": stat.st_size,
                      "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                      "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}
            if path.suffix.lower() in DOCUMENT_EXTENSIONS:
                result["content"] = self.documents.read(path)
            return ToolResult(tool, "completed", result=result, affected_files=[str(path)])
        if tool == "FILE_COPY":
            return self._copy(args, tool, run_id, chat_id)
        if tool in {"FILE_MOVE", "FILE_RENAME"}:
            return self._move(args, tool, run_id, chat_id)
        if tool == "FILE_DELETE":
            return self._delete(args, run_id, chat_id)
        if tool == "FILE_UNDO":
            return self.undo(args.get("operation_id"), approved=bool(args.get("approved")))
        if tool == "FOLDER_CREATE":
            destination = self.policy.ensure_destination(args.get("path"))
            destination.mkdir(parents=True, exist_ok=False)
            self.registry.log_operation(run_id, tool, destination=str(destination), tool_run_id=run_id, chat_id=chat_id)
            return ToolResult(tool, "completed", result={"path": str(destination)}, created_files=[str(destination)])
        if tool == "FILE_SEARCH" and args.get("roots"):
            return ToolResult(tool, "completed", result=self.indexer.refresh(args["roots"]))
        if tool == "DUPLICATE_SEARCH":
            return self._duplicates(args, tool)
        if tool == "DISK_ANALYSIS":
            return self._disk_analysis(args, tool)
        if tool in {"DOCUMENT_READ", "PDF_READ", "SPREADSHEET_READ"}:
            path = self._path(args, must_exist=True, directory=False)
            result = self.documents.read(path) if tool != "SPREADSHEET_READ" else self.spreadsheets.read(path)
            return ToolResult(tool, "completed", result=result, affected_files=[str(path)])
        if tool in {"DOCUMENT_CREATE", "PDF_CREATE", "DOCUMENT_CONVERT", "SPREADSHEET_CREATE"}:
            return self._create_document(tool, args, run_id, chat_id)
        if tool in {"AUDIO_METADATA", "AUDIO_ANALYZE"}:
            path = self._path(args, must_exist=True, directory=False)
            data = self.audio.metadata(path) if tool == "AUDIO_METADATA" else self.audio.analyze(path)
            return ToolResult(tool, "completed", result=data, affected_files=[str(path)])
        if tool == "AUDIO_COMPARE":
            first = self.policy.validate(args.get("first"), must_exist=True, directory=False)
            second = self.policy.validate(args.get("second"), must_exist=True, directory=False)
            return ToolResult(tool, "completed", result=self.audio.compare(first, second),
                             affected_files=[str(first), str(second)])
        if tool == "SYSTEM_INFO":
            return ToolResult(tool, "completed", result=self._system_info())
        if tool == "FILE_ORGANIZE":
            return self._organize(args, run_id, chat_id, bool(args.get("approved")))
        if tool == "MULTI_TOOL_TASK":
            return self._multi(args, chat_id)
        if tool in {"CHAT", "WEB_SEARCH"}:
            return ToolResult(tool, "not_implemented", errors=["handled by existing chat/web services"])
        return ToolResult(tool, "failed", errors=["route_not_implemented"])

    def _copy(self, args: dict[str, Any], tool: str, run_id: str, chat_id: str | None) -> ToolResult:
        source = self._path(args, "source", must_exist=True)
        if args.get("overwrite") and not args.get("approved"):
            raise ToolError("approval_required: overwrite requires explicit approval")
        destination = self.policy.ensure_destination(args.get("destination"), overwrite=bool(args.get("overwrite")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        self.registry.log_operation(run_id, tool, source=str(source), destination=str(destination),
                                    tool_run_id=run_id, chat_id=chat_id)
        try:
            self.registry.upsert_indexed(destination)
            # Copying preserves the source; only the new destination is added
            # to the index.  Marking the source missing would make subsequent
            # searches report a false deletion.
            self.registry.connection.commit()
        except OSError:
            pass
        if not destination.exists():
            raise ToolError("verification_failed: copy destination does not exist")
        return ToolResult(tool, "completed", result={"source": str(source), "destination": str(destination),
                                                     "operation_id": run_id},
                          affected_files=[str(source)], created_files=[str(destination)])

    def undo(self, operation_id: str | None, *, approved: bool = False) -> ToolResult:
        """Reverse a logged move/rename when both sides are unambiguous."""
        if not approved:
            raise ToolError("approval_required: undo changes files")
        if not operation_id:
            raise ToolError("operation_id_required")
        row = self.registry.connection.execute(
            "SELECT * FROM file_operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if not row or row["operation_type"] not in {"FILE_MOVE", "FILE_RENAME"}:
            raise ToolError("undo_not_available_for_operation")
        source, destination = Path(row["source"]), Path(row["destination"])
        if not destination.exists() or source.exists():
            raise ToolError("undo_conflict: source or destination changed")
        destination.rename(source)
        self.registry.log_operation(uuid.uuid4().hex, "FILE_UNDO", source=str(destination),
                                    destination=str(source), status="completed",
                                    metadata={"original_operation_id": operation_id})
        return ToolResult("FILE_UNDO", "completed",
                          result={"restored": str(source), "operation_id": operation_id},
                          affected_files=[str(destination), str(source)])

    def _move(self, args: dict[str, Any], tool: str, run_id: str, chat_id: str | None) -> ToolResult:
        source = self._path(args, "source", must_exist=True)
        if args.get("overwrite") and not args.get("approved"):
            raise ToolError("approval_required: overwrite requires explicit approval")
        destination = source.with_name(args["name"]) if tool == "FILE_RENAME" else self.policy.canonical(args.get("destination"))
        destination = self.policy.ensure_destination(destination, overwrite=bool(args.get("overwrite")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        self.registry.log_operation(run_id, tool, source=str(source), destination=str(destination),
                                    tool_run_id=run_id, chat_id=chat_id)
        try:
            self.registry.upsert_indexed(destination)
            self.registry.upsert_indexed(source, is_missing=True)
            self.registry.connection.commit()
        except OSError:
            pass
        if not destination.exists() or source.exists():
            raise ToolError("verification_failed: move or rename result is invalid")
        return ToolResult(tool, "completed", result={"source": str(source), "destination": str(destination),
                                                     "operation_id": run_id},
                          affected_files=[str(source), str(destination)])

    def _delete(self, args: dict[str, Any], run_id: str, chat_id: str | None) -> ToolResult:
        source = self._path(args, must_exist=True)
        permanent = bool(args.get("permanent"))
        if permanent and not args.get("approved"):
            raise ToolError("approval_required: permanent deletion requires explicit approval")
        if permanent:
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
            destination = None
        else:
            # ``send2trash`` uses the native Windows Recycle Bin when present.
            try:
                from send2trash import send2trash  # type: ignore
                send2trash(str(source))
                destination = "Recycle Bin"
            except ImportError:
                trash = source.parent / ".localai-trash"
                trash.mkdir(exist_ok=True)
                destination_path = _safe_name(trash / source.name)
                source.rename(destination_path)
                destination = str(destination_path)
        self.registry.log_operation(run_id, "FILE_DELETE", source=str(source),
                                    destination=destination, tool_run_id=run_id, chat_id=chat_id,
                                    metadata={"permanent": permanent})
        self.registry.upsert_indexed(source, is_missing=True)
        self.registry.connection.commit()
        if source.exists():
            raise ToolError("verification_failed: deleted path still exists")
        return ToolResult("FILE_DELETE", "completed",
                          result={"source": str(source), "recycle_destination": destination},
                          affected_files=[str(source)])

    def _duplicates(self, args: dict[str, Any], tool: str) -> ToolResult:
        rows = self.registry.search_index(directory=args.get("directory"), include_missing=False, limit=10000)
        if not rows and args.get("directory"):
            self.indexer.refresh([args["directory"]])
            rows = self.registry.search_index(directory=args.get("directory"),
                                              include_missing=False, limit=10000)
        groups: dict[tuple[int, str], list[str]] = {}
        for row in rows:
            if row["optional_hash"]:
                groups.setdefault((row["size_bytes"], row["optional_hash"]), []).append(row["path"])
            else:
                path = Path(row["path"])
                if path.exists():
                    groups.setdefault((row["size_bytes"], _sha256(path)), []).append(str(path))
        duplicates = [{"size_bytes": size, "hash": digest, "paths": paths}
                      for (size, digest), paths in groups.items() if len(paths) > 1]
        return ToolResult(tool, "completed", result={"groups": duplicates, "count": len(duplicates)})

    def _disk_analysis(self, args: dict[str, Any], tool: str) -> ToolResult:
        root = self.policy.validate(args.get("path") or Path.cwd(), must_exist=True, directory=True)
        usage = shutil.disk_usage(root)
        largest: list[dict[str, Any]] = []
        types: dict[str, int] = {}
        folders: dict[str, int] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            largest.append({"path": str(path), "size_bytes": size})
            types[path.suffix.lower() or "[none]"] = types.get(path.suffix.lower() or "[none]", 0) + size
            folders[str(path.parent)] = folders.get(str(path.parent), 0) + size
        largest.sort(key=lambda item: item["size_bytes"], reverse=True)
        return ToolResult(tool, "completed", result={
            "path": str(root), "total_bytes": usage.total, "free_bytes": usage.free,
            "used_bytes": usage.used, "largest_files": largest[:int(args.get("limit", 20))],
            "file_type_bytes": dict(sorted(types.items(), key=lambda item: item[1], reverse=True)),
            "largest_folders": [{"path": path, "size_bytes": size}
                                for path, size in sorted(folders.items(), key=lambda item: item[1], reverse=True)[:20]],
            "recommendations": "Review large files and duplicates before deleting; no cleanup was performed.",
        })

    def _create_document(self, tool: str, args: dict[str, Any], run_id: str,
                         chat_id: str | None) -> ToolResult:
        default_name = {
            "PDF_CREATE": "output.pdf", "SPREADSHEET_CREATE": "output.xlsx",
            "DOCUMENT_CREATE": "output.docx",
        }.get(tool, "output")
        destination = Path(args.get("destination") or self.generated_root / args.get("filename", default_name))
        destination = self.policy.ensure_destination(destination, overwrite=bool(args.get("overwrite")))
        if args.get("overwrite") and not args.get("approved"):
            raise ToolError("approval_required: overwrite requires explicit approval")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if tool == "SPREADSHEET_CREATE":
            self.spreadsheets.create(destination, args.get("sheets", {"Sheet1": args.get("rows", [])}),
                                     title=args.get("title"), chart=bool(args.get("chart")))
        elif tool == "DOCUMENT_CONVERT":
            source = self._path(args, "source", must_exist=True, directory=False)
            self.documents.convert(source, destination)
        else:
            if tool == "PDF_CREATE" and destination.suffix.lower() != ".pdf":
                raise ToolError("PDF_CREATE requires a .pdf destination")
            self.documents.create(destination, args.get("content", ""), title=args.get("title"))
        if not destination.is_file():
            raise ToolError("verification_failed: generated output is missing")
        file_id = self.registry.register_generated(destination, chat_id=chat_id, tool_run_id=run_id,
                                                   metadata={"tool": tool})
        self.registry.log_operation(run_id, tool, destination=str(destination),
                                    tool_run_id=run_id, chat_id=chat_id)
        return ToolResult(tool, "completed", result={"path": str(destination), "file_id": file_id},
                          created_files=[str(destination)])

    def _organize(self, args: dict[str, Any], run_id: str, chat_id: str | None,
                  approved: bool) -> ToolResult:
        root = self.policy.validate(args.get("path"), must_exist=True, directory=True)
        proposals = []
        for path in root.iterdir():
            if path.is_file() and path.suffix:
                target = root / path.suffix.lower().lstrip(".")
                proposals.append({"source": str(path), "destination": str(target / path.name)})
        if not approved:
            return ToolResult("FILE_ORGANIZE", "approval_required",
                              result={"plan": proposals, "message": "Approve the exact plan to execute."})
        for proposal in proposals:
            target = Path(proposal["destination"])
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                continue
            Path(proposal["source"]).rename(target)
            self.registry.upsert_indexed(target)
            self.registry.upsert_indexed(proposal["source"], is_missing=True)
        self.registry.connection.commit()
        self.registry.log_operation(run_id, "FILE_ORGANIZE", source=str(root), status="completed",
                                    tool_run_id=run_id, chat_id=chat_id, metadata={"count": len(proposals)})
        return ToolResult("FILE_ORGANIZE", "completed", result={"moved": proposals},
                          affected_files=[item["source"] for item in proposals])

    def _multi(self, args: dict[str, Any], chat_id: str | None) -> ToolResult:
        results = []
        for step in args.get("steps", []):
            if not isinstance(step, dict) or "tool" not in step:
                results.append({"status": "failed", "errors": ["invalid_step"]})
                continue
            result = self.run(step["tool"], step.get("arguments", {}), chat_id=chat_id,
                              approved=bool(step.get("approved", args.get("approved", False))))
            results.append(result)
            if result["status"] == "failed" and args.get("stop_on_error", False):
                break
        status = "failed" if any(item.get("status") == "failed" for item in results) else "completed"
        return ToolResult("MULTI_TOOL_TASK", status, result={"steps": results})

    @staticmethod
    def _system_info() -> dict[str, Any]:
        memory = None
        try:
            import psutil  # type: ignore
            memory = {"total_bytes": psutil.virtual_memory().total,
                      "available_bytes": psutil.virtual_memory().available}
        except ImportError:
            pass
        return {"os": platform.platform(), "python": platform.python_version(),
                "machine": platform.machine(), "processor": platform.processor(),
                "memory": memory}
