from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from local_knowledge_layer.core import DIMENSIONS, connect, counts, index, scan, search


def fake_embed(texts: list[str], prompt: str) -> np.ndarray:
    """Deterministic test double: no model download or personal data."""
    rows = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    for row, value in zip(rows, texts):
        row[0 if "approval" in value.casefold() else 1] = 1.0
    return rows


class PublicFlowTests(unittest.TestCase):
    def test_synced_folder_is_a_normal_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            synced = base / "Dropbox" / "Downloaded"
            synced.mkdir(parents=True)
            document = synced / "note.md"
            document.write_text("An approval is required before an agent acts.")
            settings = {"sources": [str(synced)], "max_file_mb": 1, "exclude_hidden": True}

            self.assertEqual(list(scan(settings, root)), [document.resolve()])
            with connect(root / "index.sqlite3") as db:
                report = index(settings, fake_embed, db, root)
                self.assertEqual(report["new"], 1)
                self.assertEqual(counts(db), (1, 1))
                matches = search("approval rules", fake_embed, db, 1)
                self.assertEqual(matches[0]["path"], str(document.resolve()))

    def test_exclusion_still_controls_synced_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            synced = base / "Google Drive"
            synced.mkdir()
            (synced / "note.txt").write_text("Synthetic text")
            settings = {"sources": [str(synced)], "exclude_paths": [str(synced)]}
            self.assertEqual(list(scan(settings, root)), [])


if __name__ == "__main__":
    unittest.main()
