"""Local command-line interface."""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time

from .core import CONFIG_PATH, DB_PATH, DIMENSIONS, ROOT, config, connect, counts, index, search, source_paths
from .model import CACHE, MODEL_ID, backend, configure_environment, embedder, load_model


def main(argv: list[str] | None = None) -> int:
    configure_environment()
    parser = argparse.ArgumentParser(prog="lkl", description="Local semantic document search")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="show environment and index state")
    sub.add_parser("status", help="show index and sources")
    sub.add_parser("index", help="update new, changed, and deleted files")
    search_parser = sub.add_parser("search", help="search indexed passages")
    search_parser.add_argument("query")
    search_parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        settings = config()
        sources = source_paths(settings)
        if args.command == "doctor":
            import torch
            try:
                uv = subprocess.check_output(["uv", "--version"], text=True).strip()
            except (OSError, subprocess.CalledProcessError):
                uv = "not available on PATH"
            device, dtype, mps = backend()
            print(f"Platform/architecture: {platform.platform()} / {platform.machine()}")
            print(f"Python: {sys.version.split()[0]} | uv: {uv} | PyTorch: {torch.__version__}")
            print(f"MPS available: {'yes' if mps else 'no'} | device: {device} | dtype: {dtype}")
            print(f"Model: {MODEL_ID} | dimensions: {DIMENSIONS}")
            print(f"Model cache: {CACHE.resolve()}")
            print(f"Database: {DB_PATH} ({'present' if DB_PATH.exists() else 'absent'})")
        if args.command in {"doctor", "status"}:
            with connect() as db:
                files, parts = counts(db)
            print(f"Indexed files/chunks: {files}/{parts}")
            print("Sources: " + ", ".join(map(str, sources)))
            return 0
        if args.command == "index":
            model, device, dtype, load_time = load_model()
            print(f"Model loaded in {load_time:.2f}s; device={device}; dtype={dtype}")
            start = time.perf_counter()
            with connect() as db:
                report = index(settings, embedder(model), db)
                files, parts = counts(db)
            print("Update: " + ", ".join(f"{key}={value}" for key, value in report.items()))
            print(f"Files/chunks: {files}/{parts}; indexing time: {time.perf_counter()-start:.2f}s")
            return 0
        if args.command == "search":
            if args.top < 1:
                parser.error("--top must be at least 1")
            if not DB_PATH.exists():
                print("Index missing: run lkl index first", file=sys.stderr)
                return 2
            model, device, dtype, load_time = load_model()
            start = time.perf_counter()
            with connect() as db:
                results = search(args.query, embedder(model), db, args.top)
            print(f"Search: {len(results)} results; device={device}; dtype={dtype}; model={load_time:.2f}s; query+ranking={time.perf_counter()-start:.2f}s")
            for result in results:
                print(f"\n{result['score']:.4f}  {result['name']}  ({result['extension']})  [chunk {result['chunk']}]")
                print(result["path"])
                print(result["excerpt"])
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
