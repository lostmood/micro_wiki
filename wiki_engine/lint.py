"""
Wiki lint engine for Day2 quality gate integration.

This module provides deterministic lint checks that can run before apply:
- Frontmatter presence and YAML validity
- Required metadata fields
- Confidence range validation
- Source reference validation
- Duplicate page_id detection
- Broken wiki link detection ([[page_id]])
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Any

import yaml


WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


@dataclass(frozen=True)
class LintIssue:
    code: str
    severity: str
    file: str
    message: str


@dataclass(frozen=True)
class LintResult:
    passed: bool
    issues: list[LintIssue]
    errors_count: int
    warnings_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "passed" if self.passed else "failed",
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "file": issue.file,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True)
class PageDoc:
    path: Path
    page_id: str | None
    frontmatter: dict[str, Any] | None
    body: str


class WikiLinter:
    """Deterministic linter for wiki markdown pages."""

    def __init__(self, required_fields: Iterable[str] | None = None):
        self.required_fields = tuple(
            required_fields
            if required_fields is not None
            else ("page_id", "title", "updated", "confidence", "source_refs")
        )

    def lint_paths(self, paths: Iterable[str | Path]) -> LintResult:
        docs = [self._load_doc(Path(p)) for p in paths]
        issues: list[LintIssue] = []
        issues.extend(self._lint_doc_basics(docs))
        issues.extend(self._lint_duplicate_page_ids(docs))
        issues.extend(self._lint_wikilinks(docs))
        return self._build_result(issues)

    def lint_wiki(self, wiki_root: str | Path) -> LintResult:
        root = Path(wiki_root)
        paths = sorted(root.rglob("*.md"))
        return self.lint_paths(paths)

    def _build_result(self, issues: list[LintIssue]) -> LintResult:
        errors = [x for x in issues if x.severity == "error"]
        warnings = [x for x in issues if x.severity == "warn"]
        return LintResult(
            passed=len(errors) == 0,
            issues=issues,
            errors_count=len(errors),
            warnings_count=len(warnings),
        )

    def _load_doc(self, path: Path) -> PageDoc:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)
        page_id = None
        if isinstance(frontmatter, dict):
            raw_page_id = frontmatter.get("page_id")
            if isinstance(raw_page_id, str) and raw_page_id.strip():
                page_id = raw_page_id.strip()
        return PageDoc(path=path, page_id=page_id, frontmatter=frontmatter, body=body)

    def _split_frontmatter(self, text: str) -> tuple[dict[str, Any] | None, str]:
        if not text.startswith("---\n"):
            return None, text

        lines = text.splitlines()
        # Search for the second --- delimiter.
        end_index = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_index = i
                break

        if end_index is None:
            return None, text

        yaml_part = "\n".join(lines[1:end_index])
        body_part = "\n".join(lines[end_index + 1 :])
        if body_part and not body_part.endswith("\n"):
            body_part += "\n"

        try:
            parsed = yaml.safe_load(yaml_part) if yaml_part.strip() else {}
        except yaml.YAMLError:
            return {"__invalid_yaml__": True}, body_part

        if not isinstance(parsed, dict):
            return {"__invalid_yaml__": True}, body_part

        return parsed, body_part

    def _lint_doc_basics(self, docs: list[PageDoc]) -> list[LintIssue]:
        issues: list[LintIssue] = []
        for doc in docs:
            file_name = str(doc.path)
            fm = doc.frontmatter
            if fm is None:
                issues.append(
                    LintIssue(
                        code="missing_frontmatter",
                        severity="error",
                        file=file_name,
                        message="Missing YAML frontmatter block at file start.",
                    )
                )
                continue

            if fm.get("__invalid_yaml__"):
                issues.append(
                    LintIssue(
                        code="invalid_frontmatter",
                        severity="error",
                        file=file_name,
                        message="Frontmatter is invalid YAML or not a mapping.",
                    )
                )
                continue

            for key in self.required_fields:
                if key not in fm:
                    issues.append(
                        LintIssue(
                            code="missing_required_field",
                            severity="error",
                            file=file_name,
                            message=f"Required field '{key}' is missing.",
                        )
                    )

            confidence = fm.get("confidence")
            if confidence is None:
                pass
            elif not isinstance(confidence, (int, float)):
                issues.append(
                    LintIssue(
                        code="invalid_confidence",
                        severity="error",
                        file=file_name,
                        message="Field 'confidence' must be a number in [0, 1].",
                    )
                )
            elif confidence < 0 or confidence > 1:
                issues.append(
                    LintIssue(
                        code="invalid_confidence",
                        severity="error",
                        file=file_name,
                        message="Field 'confidence' must be in range [0, 1].",
                    )
                )

            source_refs = fm.get("source_refs")
            if source_refs is None:
                # Already captured by missing_required_field.
                pass
            elif not isinstance(source_refs, list) or len(source_refs) == 0:
                issues.append(
                    LintIssue(
                        code="missing_source_refs",
                        severity="error",
                        file=file_name,
                        message="Field 'source_refs' must be a non-empty list.",
                    )
                )
            else:
                if not all(isinstance(x, str) and x.strip() for x in source_refs):
                    issues.append(
                        LintIssue(
                            code="missing_source_refs",
                            severity="error",
                            file=file_name,
                            message="All source_refs entries must be non-empty strings.",
                        )
                    )

        return issues

    def _lint_duplicate_page_ids(self, docs: list[PageDoc]) -> list[LintIssue]:
        issues: list[LintIssue] = []
        first_seen: dict[str, Path] = {}
        for doc in docs:
            if not doc.page_id:
                continue
            if doc.page_id not in first_seen:
                first_seen[doc.page_id] = doc.path
                continue
            issues.append(
                LintIssue(
                    code="duplicate_page_id",
                    severity="error",
                    file=str(doc.path),
                    message=(
                        f"Duplicate page_id '{doc.page_id}' already used in "
                        f"{first_seen[doc.page_id]}"
                    ),
                )
            )
        return issues

    def _lint_wikilinks(self, docs: list[PageDoc]) -> list[LintIssue]:
        issues: list[LintIssue] = []
        known_ids = {d.page_id for d in docs if d.page_id}
        for doc in docs:
            for raw in WIKILINK_RE.findall(doc.body):
                target = raw.strip()
                if not target:
                    continue
                if target not in known_ids:
                    issues.append(
                        LintIssue(
                            code="broken_wikilink",
                            severity="error",
                            file=str(doc.path),
                            message=f"Wikilink target '{target}' does not exist.",
                        )
                    )
        return issues
