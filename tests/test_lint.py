"""
Tests for WikiLinter baseline rules.
"""

import shutil
import tempfile
from pathlib import Path

from wiki_engine.lint import WikiLinter


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_lint_valid_pages_pass():
    root = Path(tempfile.mkdtemp())
    try:
        _write(
            root / "concept-transformer.md",
            """---
page_id: concept-transformer
title: Transformer
updated: 2026-04-14
confidence: 0.95
source_refs:
  - paper-attention
---
Links to [[concept-attention]].
""",
        )
        _write(
            root / "concept-attention.md",
            """---
page_id: concept-attention
title: Attention
updated: 2026-04-14
confidence: 0.90
source_refs:
  - paper-attention
---
Attention body.
""",
        )

        result = WikiLinter().lint_wiki(root)
        assert result.passed
        assert result.errors_count == 0
    finally:
        shutil.rmtree(root)


def test_missing_frontmatter_fails():
    root = Path(tempfile.mkdtemp())
    try:
        _write(root / "no-fm.md", "no frontmatter\n")
        result = WikiLinter().lint_wiki(root)
        assert not result.passed
        assert any(issue.code == "missing_frontmatter" for issue in result.issues)
    finally:
        shutil.rmtree(root)


def test_invalid_confidence_fails():
    root = Path(tempfile.mkdtemp())
    try:
        _write(
            root / "bad-confidence.md",
            """---
page_id: concept-x
title: X
updated: 2026-04-14
confidence: 1.5
source_refs:
  - src-1
---
Body.
""",
        )
        result = WikiLinter().lint_wiki(root)
        assert not result.passed
        assert any(issue.code == "invalid_confidence" for issue in result.issues)
    finally:
        shutil.rmtree(root)


def test_missing_source_refs_fails():
    root = Path(tempfile.mkdtemp())
    try:
        _write(
            root / "bad-sources.md",
            """---
page_id: concept-x
title: X
updated: 2026-04-14
confidence: 0.7
source_refs: []
---
Body.
""",
        )
        result = WikiLinter().lint_wiki(root)
        assert not result.passed
        assert any(issue.code == "missing_source_refs" for issue in result.issues)
    finally:
        shutil.rmtree(root)


def test_broken_wikilink_and_duplicate_id_fail():
    root = Path(tempfile.mkdtemp())
    try:
        _write(
            root / "a.md",
            """---
page_id: concept-a
title: A
updated: 2026-04-14
confidence: 0.8
source_refs:
  - src-a
---
See [[missing-page]].
""",
        )
        _write(
            root / "b.md",
            """---
page_id: concept-a
title: B
updated: 2026-04-14
confidence: 0.8
source_refs:
  - src-b
---
Body.
""",
        )
        result = WikiLinter().lint_wiki(root)
        assert not result.passed
        codes = {issue.code for issue in result.issues}
        assert "duplicate_page_id" in codes
        assert "broken_wikilink" in codes
    finally:
        shutil.rmtree(root)
