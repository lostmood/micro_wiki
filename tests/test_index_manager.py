"""
Tests for IndexManager (Day3).
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from wiki_engine.index_manager import IndexManager, IndexOperation


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_replay_and_compaction():
    root = Path(tempfile.mkdtemp())
    try:
        manager = IndexManager(str(root), compaction_threshold=3)

        manager.append_operation(
            IndexOperation("op-1", 1.0, "add", "p1", "Title 1", "Summary 1", "concepts")
        )
        manager.append_operation(
            IndexOperation("op-2", 2.0, "update", "p1", "Title 1+", "Summary 1+", "concepts")
        )
        manager.append_operation(
            IndexOperation("op-3", 3.0, "add", "p2", "Title 2", "Summary 2", "entities")
        )

        assert manager.should_compact()
        manager.compact()

        index_md = (root / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "[[p1]] Title 1+" in index_md
        assert "[[p2]] Title 2" in index_md
        assert manager.index_ops_file.read_text(encoding="utf-8") == ""
    finally:
        shutil.rmtree(root)


def test_record_patch_appends_ops():
    root = Path(tempfile.mkdtemp())
    try:
        _write(
            root / "wiki" / "page-a.md",
            """---
page_id: page-a
title: Page A
updated: 2026-04-14
category: concepts
confidence: 0.9
source_refs: [src]
---
Summary line.
""",
        )

        manager = IndexManager(str(root), compaction_threshold=100)
        patch = SimpleNamespace(
            operation="update",
            affected_pages=["page-a"],
        )
        manager.record_patch(patch)

        lines = manager.index_ops_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        op = json.loads(lines[0])
        assert op["operation"] == "update"
        assert op["page_id"] == "page-a"
        assert op["title"] == "Page A"
        assert op["category"] == "concepts"
    finally:
        shutil.rmtree(root)


def test_should_compact_by_interval_without_meta():
    root = Path(tempfile.mkdtemp())
    try:
        manager = IndexManager(
            str(root),
            compaction_threshold=100,
            max_compaction_interval_seconds=1,
        )
        manager.append_operation(
            IndexOperation("op-1", 1.0, "add", "p1", "Title 1", "Summary 1", "concepts")
        )

        stale_ts = time.time() - 5
        os.utime(manager.index_ops_file, (stale_ts, stale_ts))

        assert manager.should_compact()
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    test_replay_and_compaction()
    test_record_patch_appends_ops()
    test_should_compact_by_interval_without_meta()
    print("\n✓ All index manager tests passed")
