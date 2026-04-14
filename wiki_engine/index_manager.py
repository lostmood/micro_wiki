"""
Index manager for Day3: append-only index.ops + periodic compaction.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import time
import uuid
import fcntl
from contextlib import contextmanager
from typing import Any

import yaml


@dataclass(frozen=True)
class IndexOperation:
    op_id: str
    timestamp: float
    operation: str  # "add" / "update" / "remove"
    page_id: str
    title: str
    summary: str
    category: str


class IndexManager:
    """
    Maintains append-only index operations and compacts them into wiki/index.md.
    """

    def __init__(
        self,
        wiki_root: str,
        compaction_threshold: int = 100,
        max_compaction_interval_seconds: int = 24 * 60 * 60,
    ):
        self.wiki_root = Path(wiki_root)
        self.index_dir = self.wiki_root / ".index"
        self.index_ops_file = self.index_dir / "index.ops.jsonl"
        self.index_meta_file = self.index_dir / "meta.json"
        self.index_lock_file = self.index_dir / ".index.lock"
        self.index_markdown_file = self.wiki_root / "wiki" / "index.md"

        self.compaction_threshold = compaction_threshold
        self.max_compaction_interval_seconds = max_compaction_interval_seconds

        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.wiki_root / "wiki").mkdir(parents=True, exist_ok=True)
        self.index_lock_file.touch(exist_ok=True)

    def record_patch(self, patch: Any):
        """
        Record index operations generated from a workflow patch.
        """
        with self._index_lock():
            op_type = self._map_patch_operation(patch.operation)
            for page_id in patch.affected_pages:
                title, summary, category = self._read_page_metadata(page_id)
                op = IndexOperation(
                    op_id=f"op-{uuid.uuid4().hex[:12]}",
                    timestamp=time.time(),
                    operation=op_type,
                    page_id=page_id,
                    title=title,
                    summary=summary,
                    category=category,
                )
                self._append_operation_unlocked(op)

            if self._should_compact_unlocked():
                self._compact_unlocked()

    def append_operation(self, op: IndexOperation):
        with self._index_lock():
            self._append_operation_unlocked(op)

    def should_compact(self) -> bool:
        with self._index_lock():
            return self._should_compact_unlocked()

    def compact(self):
        with self._index_lock():
            self._compact_unlocked()

    @contextmanager
    def _index_lock(self):
        with self.index_lock_file.open("r", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append_operation_unlocked(self, op: IndexOperation):
        with self.index_ops_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(op), ensure_ascii=False) + "\n")

    def _should_compact_unlocked(self) -> bool:
        if not self.index_ops_file.exists():
            return False

        line_count = self._count_lines(self.index_ops_file)
        if line_count >= self.compaction_threshold:
            return True

        if line_count == 0:
            return False

        last_compaction = self._get_last_compaction_time()
        if last_compaction is not None:
            reference_ts = last_compaction
        else:
            reference_ts = self.index_ops_file.stat().st_mtime

        return (time.time() - reference_ts) >= self.max_compaction_interval_seconds

    def _compact_unlocked(self):
        state = self._replay_ops()
        self._write_index_markdown(state)
        self.index_ops_file.write_text("", encoding="utf-8")
        self._set_last_compaction_time(time.time())

    def _replay_ops(self) -> dict[str, dict[str, str]]:
        state: dict[str, dict[str, str]] = {}
        if not self.index_ops_file.exists():
            return state

        with self.index_ops_file.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                op = json.loads(line)
                page_id = op["page_id"]
                if op["operation"] == "remove":
                    state.pop(page_id, None)
                    continue
                state[page_id] = {
                    "title": op["title"],
                    "summary": op["summary"],
                    "category": op["category"],
                }
        return state

    def _write_index_markdown(self, state: dict[str, dict[str, str]]):
        by_category: dict[str, list[tuple[str, dict[str, str]]]] = {}
        for page_id, entry in state.items():
            category = entry.get("category") or "uncategorized"
            by_category.setdefault(category, []).append((page_id, entry))

        lines: list[str] = []
        lines.append("# Wiki Index")
        lines.append("")
        lines.append(f"_Generated at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC_")
        lines.append("")

        for category in sorted(by_category):
            lines.append(f"## {category}")
            lines.append("")
            for page_id, entry in sorted(by_category[category], key=lambda x: x[0]):
                title = entry["title"] or page_id
                summary = entry["summary"] or ""
                lines.append(f"- [[{page_id}]] {title}")
                if summary:
                    lines.append(f"  - {summary}")
            lines.append("")

        self.index_markdown_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _map_patch_operation(self, operation: str) -> str:
        if operation == "create":
            return "add"
        if operation == "update":
            return "update"
        if operation == "delete":
            return "remove"
        return "update"

    def _read_page_metadata(self, page_id: str) -> tuple[str, str, str]:
        page_path = self.wiki_root / "wiki" / f"{page_id}.md"
        if not page_path.exists():
            return page_id, "", "uncategorized"

        text = page_path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)
        title = page_id
        category = "uncategorized"
        if isinstance(frontmatter, dict):
            raw_title = frontmatter.get("title")
            if isinstance(raw_title, str) and raw_title.strip():
                title = raw_title.strip()
            raw_category = frontmatter.get("category")
            if isinstance(raw_category, str) and raw_category.strip():
                category = raw_category.strip()

        summary = self._extract_summary(body)
        return title, summary, category

    def _split_frontmatter(self, text: str) -> tuple[dict[str, Any] | None, str]:
        if not text.startswith("---\n"):
            return None, text
        lines = text.splitlines()
        end_index = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_index = i
                break
        if end_index is None:
            return None, text
        yaml_part = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :])
        try:
            parsed = yaml.safe_load(yaml_part) if yaml_part.strip() else {}
        except yaml.YAMLError:
            parsed = None
        return parsed if isinstance(parsed, dict) else None, body

    def _extract_summary(self, body: str) -> str:
        for line in body.splitlines():
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                return candidate[:180]
        return ""

    def _get_last_compaction_time(self) -> float | None:
        if not self.index_meta_file.exists():
            return None
        try:
            data = json.loads(self.index_meta_file.read_text(encoding="utf-8"))
            value = data.get("last_compaction")
            if isinstance(value, (int, float)):
                return float(value)
        except json.JSONDecodeError:
            return None
        return None

    def _set_last_compaction_time(self, ts: float):
        self.index_meta_file.write_text(json.dumps({"last_compaction": ts}), encoding="utf-8")

    def _count_lines(self, file_path: Path) -> int:
        with file_path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
