"""Read-only source scanning and a local SQLite/NumPy index."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import tomllib
from pathlib import Path
from typing import Callable

import numpy as np
from .parsers import DOC_EXTENSIONS, extract as extract_document

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "database" / "index.sqlite3"
CONFIG_PATH = ROOT / "config" / "config.toml"
EXTENSIONS = DOC_EXTENSIONS
DIMENSIONS = 256


def config(path: Path = CONFIG_PATH) -> dict:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data.get("sources"), list) or not data["sources"]:
        raise ValueError("config.toml: sources must be a non-empty list")
    return data


def source_paths(settings: dict, root: Path = ROOT) -> list[Path]:
    paths = []
    for item in settings["sources"]:
        if not isinstance(item, str):
            raise ValueError("config.toml: each source must be a path string")
        path = Path(item).expanduser()
        path = (path if path.is_absolute() else root / path).resolve()
        if path == root.resolve():
            raise ValueError("Cannot index the project root")
        if path != root / "sample_data" and root.resolve() in path.parents:
            raise ValueError("Cannot index an internal project directory except sample_data")
        if not path.is_dir():
            raise ValueError(f"Source directory does not exist: {path}")
        paths.append(path)
    return paths


def document_stat(path: Path) -> tuple[int, int]:
    """Return total bytes and latest mtime for a file or iWork package."""
    if path.is_file():
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns
    if not path.is_dir() or path.suffix.lower() not in {'.pages', '.numbers'}:
        raise ValueError(f'Unsupported package: {path}')
    size, mtime = 0, path.stat().st_mtime_ns
    for child in path.rglob('*'):
        if child.is_symlink():
            raise ValueError(f'Symlink inside package: {child}')
        if child.is_file():
            stat = child.stat()
            size += stat.st_size
            mtime = max(mtime, stat.st_mtime_ns)
    return size, mtime


def document_hash(path: Path) -> str:
    digest = hashlib.sha256()
    children = [path] if path.is_file() else sorted(child for child in path.rglob('*') if child.is_file())
    for child in children:
        if child.is_symlink():
            raise ValueError(f'Symlink inside package: {child}')
        if child != path:
            digest.update(str(child.relative_to(path)).encode('utf-8'))
        with child.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def scan(settings: dict, root: Path = ROOT, onerror=None):
    """Yield eligible regular files without following symlinks or excluded trees."""
    excluded = set(settings.get("exclude_dirs", [])) | {".git", ".venv", "node_modules", "__pycache__", ".cache", "dist", "build"}
    excluded_files = set(settings.get("exclude_files", []))
    excluded_paths = set()
    for item in settings.get("exclude_paths", []):
        path = Path(item).expanduser()
        excluded_paths.add((path if path.is_absolute() else root / path).resolve())
    max_size = int(settings.get("max_file_mb", 10)) * 1024 * 1024
    skip_hidden = bool(settings.get("exclude_hidden", False))
    root = root.resolve()

    def note(path, error):
        if onerror is not None:
            onerror(Path(path), error)

    for source in source_paths(settings, root):
        if source in excluded_paths:
            continue
        for directory, dirs, files in os.walk(source, followlinks=False, onerror=lambda error: note(error.filename, error)):
            current = Path(directory)
            kept = []
            for name in dirs:
                child = current / name
                if name in excluded or (skip_hidden and name.startswith(".")) or child == root or child in excluded_paths or child.is_symlink():
                    continue
                if child.suffix.lower() in {'.pages', '.numbers'}:
                    try:
                        if document_stat(child)[0] <= max_size:
                            yield child
                    except (OSError, ValueError) as exc:
                        note(child, exc)
                    continue
                kept.append(name)
            dirs[:] = sorted(kept)
            for name in sorted(files):
                path = current / name
                if name == ".DS_Store" or name in excluded_files or (skip_hidden and name.startswith(".")) or path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                    continue
                try:
                    if document_stat(path)[0] <= max_size:
                        yield path
                except OSError as exc:
                    note(path, exc)


def normalize_text(value: str) -> str:
    """Turn RTF-style UTF-16 surrogate pairs into valid Unicode for the tokenizer."""
    return value.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')


def extract(path: Path) -> str | None:
    value = extract_document(path)
    return normalize_text(value) if value is not None else None


def chunks(text: str, size: int = 180, overlap: int = 30, max_chars: int = 2000) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size or max_chars < 100:
        raise ValueError("Invalid chunk parameters")
    words = []
    for word in text.split():
        words.extend(word[i:i + max_chars] for i in range(0, len(word), max_chars))
    result = []
    start = 0
    while start < len(words):
        end, length = start, 0
        while end < len(words) and end - start < size:
            added = len(words[end]) + (1 if end > start else 0)
            if length + added > max_chars:
                break
            length += added
            end += 1
        if end == start:
            end += 1
        result.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        local_overlap = overlap if end - start == size else min(overlap, max(1, (end - start) // 6))
        start = max(start + 1, end - local_overlap)
    return result


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY, filename TEXT NOT NULL, extension TEXT NOT NULL,
          size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
        CREATE TABLE IF NOT EXISTS chunks (
          file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
          chunk_index INTEGER NOT NULL, text TEXT NOT NULL, vector BLOB NOT NULL,
          PRIMARY KEY (file_path, chunk_index)
        );
    """)
    return db


def validate_vectors(vectors, count: int) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.shape != (count, DIMENSIONS) or not np.isfinite(arr).all():
        raise ValueError(f"Invalid embedding shape {arr.shape}; expected ({count}, {DIMENSIONS})")
    norms = np.linalg.norm(arr, axis=1)
    if (norms <= 0).any():
        raise ValueError("Zero-norm embedding")
    return arr / norms[:, None]


def index(settings: dict, embed: Callable[[list[str], str], np.ndarray], db: sqlite3.Connection, root: Path = ROOT) -> dict:
    """Update eligible files incrementally; keep old rows under unreadable trees."""
    seen: set[str] = set()
    failed_paths: set[Path] = set()
    report = {"new": 0, "updated": 0, "unchanged": 0, "deleted": 0, "skipped": 0, "errors": 0}
    error_log = root / "logs" / "index_errors.jsonl"
    logged_legacy = set()
    if error_log.exists():
        for line in error_log.open(encoding="utf-8"):
            try:
                entry = json.loads(line)
                if entry.get("kind") == "legacy_unsupported":
                    logged_legacy.add(entry.get("path"))
            except json.JSONDecodeError:
                continue
    started = time.monotonic()
    processed = 0
    # Prune old unsupported rows.
    with db:
        for identity, extension in list(db.execute("SELECT path, extension FROM files")):
            if extension not in EXTENSIONS:
                db.execute("DELETE FROM files WHERE path=?", (identity,))
                report["deleted"] += 1

    def record(kind: str, path: Path, error: Exception | str):
        if kind == "legacy_unsupported":
            if str(path) in logged_legacy:
                return
            logged_legacy.add(str(path))
        error_log.parent.mkdir(parents=True, exist_ok=True)
        with error_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "path": str(path), "error": str(error)}, ensure_ascii=False) + "\n")

    def scan_error(path: Path, error: Exception):
        failed_paths.add(path)
        report["errors"] += 1
        record("scan", path, error)
        print(f"Scan error: {path}: {error}", flush=True)

    for path in scan(settings, root, onerror=scan_error):
        processed += 1
        identity = str(path.resolve())
        seen.add(identity)
        try:
            if path.suffix.lower() == '.doc':
                report["skipped"] += 1
                record("legacy_unsupported", path, "legacy .doc has no supported local parser")
                continue
            size, mtime_ns = document_stat(path)
            previous = db.execute("SELECT size, mtime_ns, sha256 FROM files WHERE path=?", (identity,)).fetchone()
            if previous and previous[0] == size and previous[1] == mtime_ns:
                report["unchanged"] += 1
                continue
            digest = document_hash(path)
            if previous and previous[2] == digest:
                with db:
                    db.execute("UPDATE files SET size=?, mtime_ns=? WHERE path=?", (size, mtime_ns, identity))
                report["unchanged"] += 1
                continue
            duplicate = db.execute("SELECT path FROM files WHERE sha256=? AND path<>? LIMIT 1", (digest, identity)).fetchone()
            if duplicate:
                with db:
                    db.execute("DELETE FROM files WHERE path=?", (identity,))
                    db.execute("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", (identity, path.name, path.suffix.lower(), size, mtime_ns, digest))
                    db.execute("INSERT INTO chunks SELECT ?, chunk_index, text, vector FROM chunks WHERE file_path=?", (identity, duplicate[0]))
                report["updated" if previous else "new"] += 1
                continue
            try:
                text = extract(path)
            except Exception as exc:
                report["skipped"] += 1
                report["errors"] += 1
                record("extract", path, exc)
                print(f"Skipped: {path}: {exc}", flush=True)
                continue
            if not text:
                record("legacy_unsupported" if path.suffix.lower() == '.doc' else "no_extractable_text", path, "no extractable text")
                if previous:
                    with db:
                        db.execute("DELETE FROM files WHERE path=?", (identity,))
                report["skipped"] += 1
                continue
            parts = chunks(text)
            # A failed embedding or database write is systemic: stop and preserve completed files.
            vectors = validate_vectors(embed(parts, "Document"), len(parts))
            with db:
                db.execute("DELETE FROM files WHERE path=?", (identity,))
                db.execute("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", (identity, path.name, path.suffix.lower(), size, mtime_ns, digest))
                db.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?)", [(identity, i, part, vectors[i].tobytes()) for i, part in enumerate(parts)])
            report["updated" if previous else "new"] += 1
        except (OSError, ValueError) as exc:
            report["skipped"] += 1
            report["errors"] += 1
            record("file", path, exc)
            print(f"Skipped: {path}: {exc}", flush=True)
        finally:
            if processed % 50 == 0:
                print(f"Progress: {processed} eligible files, {report['new']} new, {report['updated']} updated, {report['skipped']} skipped, {time.monotonic()-started:.0f}s", flush=True)
    old = [row[0] for row in db.execute("SELECT path FROM files")]
    with db:
        for identity in old:
            recorded = Path(identity)
            if identity not in seen and not any(recorded == failed or failed in recorded.parents for failed in failed_paths):
                db.execute("DELETE FROM files WHERE path=?", (identity,))
                report["deleted"] += 1
    return report


def search(query: str, embed: Callable[[list[str], str], np.ndarray], db: sqlite3.Connection, limit: int = 10) -> list[dict]:
    query_vector = validate_vectors(embed([query], "SearchQuery"), 1)[0]
    best_by_content: dict[str, dict] = {}
    rows = db.execute("SELECT f.path, f.filename, f.extension, f.sha256, c.chunk_index, c.text, c.vector FROM chunks c JOIN files f ON f.path=c.file_path")
    for path, name, extension, digest, number, text, blob in rows:
        vector = np.frombuffer(blob, dtype=np.float32)
        if vector.shape != (DIMENSIONS,) or not np.isfinite(vector).all():
            raise ValueError(f"Corrupt vector for {path}, chunk {number}")
        score = float(np.dot(query_vector, vector))
        previous = best_by_content.get(digest)
        if previous is None or score > previous["score"]:
            best_by_content[digest] = {"score": score, "path": path, "name": name, "extension": extension, "chunk": number, "excerpt": text[:280]}
    return sorted(best_by_content.values(), key=lambda result: result["score"], reverse=True)[:limit]


def counts(db: sqlite3.Connection) -> tuple[int, int]:
    return db.execute("SELECT COUNT(*) FROM files").fetchone()[0], db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
