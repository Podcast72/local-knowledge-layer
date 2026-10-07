"""Create a personal plugin copy with local paths outside Git tracking."""
from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "plugin" / "maclocal"
    destination = root / ".local-plugin" / "maclocal"
    if destination.exists():
        raise SystemExit(f"Plugin copy already exists; review it before replacing: {destination}")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".mcp.json.template"))
    template = (source / ".mcp.json.template").read_text(encoding="utf-8")
    config = (template.replace("__PROJECT_ROOT__", str(root))
              .replace("__PYTHON_PATH__", str(root / ".venv" / "bin" / "python"))
              .replace("__SERVER_PATH__", str(destination / "server" / "mcp_server.py")))
    (destination / ".mcp.json").write_text(config, encoding="utf-8")
    print(f"Personal plugin prepared at: {destination}")
    print("This directory is ignored by Git. Add it as a personal plugin source in your client.")


if __name__ == "__main__":
    main()
