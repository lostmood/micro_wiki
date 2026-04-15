"""
MCP Tools for Wiki Engine.

Exposes workflow engine functionality through MCP tool interface.
All write operations delegate to workflow.propose_patch() and workflow.apply_patch().
All read operations have zero side effects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import subprocess
import time
import re
import hashlib
import uuid
import json
import yaml

from wiki_engine.acl import ApprovalACL
from wiki_engine.lint import WikiLinter
from wiki_engine.workflow import WikiWorkflow

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


def _candidate_page_paths(root: Path, page_id: str) -> List[Path]:
    return [
        root / "wiki" / f"{page_id}.md",
        root / "wiki" / "concepts" / f"{page_id}.md",
        root / "wiki" / "entities" / f"{page_id}.md",
        root / "wiki" / "explorations" / f"{page_id}.md",
    ]


def _resolve_existing_page_path(root: Path, page_id: str) -> Path | None:
    for candidate in _candidate_page_paths(root, page_id):
        if candidate.exists():
            return candidate
    return None


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---\n"):
        return None, text

    lines = text.splitlines()
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, text

    frontmatter_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    if body and not body.endswith("\n"):
        body += "\n"

    try:
        frontmatter = yaml.safe_load(frontmatter_text) if frontmatter_text.strip() else {}
    except yaml.YAMLError:
        return None, body

    return frontmatter if isinstance(frontmatter, dict) else None, body


def _scan_wiki_pages(wiki_root: str) -> dict[str, dict[str, Any]]:
    root = Path(wiki_root)
    wiki_dir = root / "wiki"
    pages: dict[str, dict[str, Any]] = {}
    if not wiki_dir.exists():
        return pages

    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name == "index.md":
            continue
        text = md_file.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        rel_page_id = str(md_file.relative_to(wiki_dir).with_suffix("")).replace("/", "-")
        page_id = rel_page_id
        title = rel_page_id
        if isinstance(frontmatter, dict):
            raw_page_id = frontmatter.get("page_id")
            if isinstance(raw_page_id, str) and raw_page_id.strip():
                page_id = raw_page_id.strip()
            raw_title = frontmatter.get("title")
            if isinstance(raw_title, str) and raw_title.strip():
                title = raw_title.strip()
        pages[page_id] = {"title": title, "path": str(md_file), "body": body}
    return pages


def _extract_wikilinks(body: str) -> set[str]:
    return {raw.strip() for raw in WIKILINK_RE.findall(body) if raw.strip()}


def _sanitize_page_id(raw_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw_name).strip("-").lower()
    return normalized or "ingested-page"


def _load_pending_patch_records(root: Path) -> List[dict[str, Any]]:
    pending_dir = root / ".pending"
    records: List[dict[str, Any]] = []
    if not pending_dir.exists():
        return records

    for patch_file in sorted(pending_dir.glob("*.json")):
        try:
            records.append(json.loads(patch_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records


def _load_conflict_resolutions(root: Path) -> dict[str, dict[str, Any]]:
    resolution_file = root / ".audit" / "conflict_resolutions.jsonl"
    resolutions: dict[str, dict[str, Any]] = {}
    if not resolution_file.exists():
        return resolutions

    for raw_line in resolution_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        conflict_id = record.get("conflict_id")
        if isinstance(conflict_id, str) and conflict_id:
            resolutions[conflict_id] = record
    return resolutions


def _generate_change_id() -> str:
    return f"ch-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def wiki_read(wiki_root: str, page_id: str) -> Dict[str, Any]:
    """
    Read a wiki page.

    Args:
        wiki_root: Path to wiki root directory
        page_id: Page identifier

    Returns:
        Success: {
            "status": "success",
            "page_id": str,
            "title": str,
            "content": str,
            "metadata": dict
        }

        Failure: {
            "status": "failed",
            "reason": "page_not_found",
            "message": str
        }
    """
    root = Path(wiki_root)

    # Search for page in subdirectories (same order as workflow)
    search_paths = [
        root / "wiki" / "concepts" / f"{page_id}.md",
        root / "wiki" / "entities" / f"{page_id}.md",
        root / "wiki" / "explorations" / f"{page_id}.md",
        root / "wiki" / f"{page_id}.md",
    ]

    page_path = None
    for path in search_paths:
        if path.exists():
            page_path = path
            break

    if not page_path:
        return {
            "status": "failed",
            "reason": "page_not_found",
            "message": f"Page '{page_id}' does not exist"
        }

    # Read page content
    content = page_path.read_text(encoding="utf-8")

    # Parse frontmatter
    metadata = {}
    title = page_id

    lines = content.split("\n")
    if lines and lines[0].strip() == "---":
        # Find end of frontmatter
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx:
            import yaml
            frontmatter_text = "\n".join(lines[1:end_idx])
            try:
                metadata = yaml.safe_load(frontmatter_text) or {}
                title = metadata.get("title", page_id)
            except yaml.YAMLError:
                pass

    return {
        "status": "success",
        "page_id": page_id,
        "title": title,
        "content": content,
        "metadata": metadata
    }


def wiki_status(wiki_root: str) -> Dict[str, Any]:
    """
    Get wiki status and statistics.

    Args:
        wiki_root: Path to wiki root directory

    Returns:
        {
            "status": "success",
            "total_pages": int,
            "pending_patches": int,
            "last_update": str,
            "health": "healthy"
        }
    """
    root = Path(wiki_root)
    wiki_dir = root / "wiki"
    pending_dir = root / ".pending"

    # Count total pages
    total_pages = 0
    if wiki_dir.exists():
        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name != "index.md":  # Exclude index
                total_pages += 1

    # Count pending patches
    pending_patches = 0
    if pending_dir.exists():
        pending_patches = len(list(pending_dir.glob("*.json")))

    # Get last update time from git
    last_update = None
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=wiki_root,
            capture_output=True,
            text=True,
            check=True
        )
        last_update = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Git not available or no commits
        last_update = None

    return {
        "status": "success",
        "total_pages": total_pages,
        "pending_patches": pending_patches,
        "last_update": last_update,
        "health": "healthy"
    }


def wiki_search(wiki_root: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Search wiki pages by query.

    Args:
        wiki_root: Path to wiki root directory
        query: Search query string
        limit: Maximum number of results

    Returns:
        {
            "status": "success",
            "results": [
                {
                    "page_id": str,
                    "title": str,
                    "summary": str,
                    "relevance_score": float
                }
            ],
            "total": int
        }
    """
    root = Path(wiki_root)
    wiki_dir = root / "wiki"

    if not wiki_dir.exists():
        return {
            "status": "success",
            "results": [],
            "total": 0
        }

    results = []
    query_lower = query.lower()

    # Simple string matching search
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name == "index.md":
            continue

        # Extract page_id from path
        rel_path = md_file.relative_to(wiki_dir)
        page_id = str(rel_path.with_suffix("")).replace("/", "-")

        # Read content
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Parse frontmatter for title
        title = page_id
        summary = ""
        lines = content.split("\n")

        if lines and lines[0].strip() == "---":
            end_idx = None
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    end_idx = i
                    break

            if end_idx:
                import yaml
                try:
                    metadata = yaml.safe_load("\n".join(lines[1:end_idx])) or {}
                    title = metadata.get("title", page_id)
                except yaml.YAMLError:
                    pass

                # Extract summary from body
                body_lines = lines[end_idx + 1:]
                for line in body_lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        summary = stripped[:180]
                        break

        # Calculate relevance score (simple string matching)
        relevance_score = 0.0
        content_lower = content.lower()
        title_lower = title.lower()

        if query_lower in title_lower:
            relevance_score += 0.8
        if query_lower in content_lower:
            relevance_score += 0.2

        if relevance_score > 0:
            results.append({
                "page_id": page_id,
                "title": title,
                "summary": summary,
                "relevance_score": relevance_score
            })

    # Sort by relevance and limit
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    results = results[:limit]

    return {
        "status": "success",
        "results": results,
        "total": len(results)
    }


def wiki_propose_patch(
    wiki_root: str,
    agent_id: str,
    operation: str,
    pages: List[str],
    diff: str,
    confidence: float,
    sources: List[str]
) -> Dict[str, Any]:
    """
    Propose a patch for review.

    Delegates to workflow.propose_patch().

    Args:
        wiki_root: Path to wiki root directory
        agent_id: ID of the agent proposing the patch
        operation: Operation type ("create" / "update" / "delete")
        pages: List of affected page IDs
        diff: Unified diff of changes
        confidence: Agent's confidence score (0.0-1.0)
        sources: List of source references

    Returns:
        Always returns status="success" (even if lint fails).
        Check lint_status field to determine if content is valid.

        {
            "status": "success",
            "patch_id": str,
            "requires_approval": bool,
            "confidence": float,
            "lint_status": "passed" | "failed",
            "lint_errors": list | null
        }
    """
    workflow = WikiWorkflow(wiki_root)
    return workflow.propose_patch(
        agent_id=agent_id,
        operation=operation,
        pages=pages,
        diff=diff,
        confidence=confidence,
        sources=sources
    )


def wiki_apply_patch(
    wiki_root: str,
    patch_id: str,
    signed_approval: Dict[str, Any],
    expected_base_commit: str
) -> Dict[str, Any]:
    """
    Apply an approved patch.

    Delegates to workflow.apply_patch().

    Args:
        wiki_root: Path to wiki root directory
        patch_id: ID of the patch to apply
        signed_approval: Signed approval dict with all required fields
        expected_base_commit: Expected base commit hash

    Returns:
        Success: {
            "status": "success",
            "change_id": str,
            "commit_hash": str,
            "applied_at": float
        }

        Failure (error codes from workflow - 原样透传): {
            "status": "failed",
            "reason": str,
            "message": str
        }
    """
    workflow = WikiWorkflow(wiki_root)
    return workflow.apply_patch(
        patch_id=patch_id,
        signed_approval=signed_approval,
        expected_base_commit=expected_base_commit
    )


def wiki_graph_neighbors(wiki_root: str, page_id: str, depth: int = 1) -> Dict[str, Any]:
    """
    Get neighboring pages in the wiki graph using wikilinks.
    """
    if depth < 1 or depth > 3:
        return {
            "status": "failed",
            "reason": "invalid_depth",
            "message": "depth must be in range [1, 3]",
        }

    pages = _scan_wiki_pages(wiki_root)
    if page_id not in pages:
        return {
            "status": "failed",
            "reason": "page_not_found",
            "message": f"Page '{page_id}' does not exist",
        }

    outgoing: dict[str, set[str]] = {pid: set() for pid in pages}
    incoming: dict[str, set[str]] = {pid: set() for pid in pages}

    for src_page_id, meta in pages.items():
        for target in _extract_wikilinks(meta["body"]):
            if target not in pages:
                continue
            outgoing[src_page_id].add(target)
            incoming[target].add(src_page_id)

    visited = {page_id}
    queue: list[tuple[str, int]] = [(page_id, 0)]
    while queue:
        current, current_depth = queue.pop(0)
        if current_depth >= depth:
            continue
        neighbors = outgoing.get(current, set()) | incoming.get(current, set())
        for neighbor in sorted(neighbors):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, current_depth + 1))

    nodes = [
        {"page_id": pid, "title": pages[pid]["title"]}
        for pid in sorted(visited)
    ]
    edges = []
    for src_page_id in sorted(visited):
        for target in sorted(outgoing.get(src_page_id, set())):
            if target in visited:
                edges.append({"from": src_page_id, "to": target, "type": "references"})

    return {
        "status": "success",
        "page_id": page_id,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
    }


def wiki_ingest(wiki_root: str, source_path: str, agent_id: str) -> Dict[str, Any]:
    """
    Ingest a source file by proposing a workflow patch.
    """
    source = Path(source_path)
    if not source.is_absolute():
        source = (Path(wiki_root) / source).resolve()
    if not source.exists() or not source.is_file():
        return {
            "status": "failed",
            "reason": "source_not_found",
            "message": f"Source file '{source_path}' does not exist",
        }

    content = source.read_text(encoding="utf-8")
    if not content.strip():
        return {
            "status": "failed",
            "reason": "empty_source",
            "message": f"Source file '{source_path}' is empty",
        }

    page_id = _sanitize_page_id(source.stem)
    root = Path(wiki_root)
    operation = "update" if _resolve_existing_page_path(root, page_id) else "create"

    workflow = WikiWorkflow(wiki_root)
    result = workflow.propose_patch(
        agent_id=agent_id,
        operation=operation,
        pages=[page_id],
        diff=content,
        confidence=0.9,
        sources=[f"file:{source}"],
    )
    result["affected_pages"] = [page_id]
    result["source_path"] = str(source)
    return result


def wiki_list_conflicts(wiki_root: str, status: str = "pending") -> Dict[str, Any]:
    """
    List page-overlap conflicts across pending patches.
    """
    if status not in {"pending", "resolved", "all"}:
        return {
            "status": "failed",
            "reason": "invalid_status",
            "message": "status must be one of: pending, resolved, all",
        }

    root = Path(wiki_root)
    patch_records = _load_pending_patch_records(root)
    page_to_patches: dict[str, list[dict[str, Any]]] = {}
    for patch in patch_records:
        patch_id = patch.get("patch_id")
        pages = patch.get("affected_pages", [])
        if not isinstance(patch_id, str) or not isinstance(pages, list):
            continue
        for page in pages:
            if isinstance(page, str) and page:
                page_to_patches.setdefault(page, []).append(patch)

    resolutions = _load_conflict_resolutions(root)
    conflicts: List[Dict[str, Any]] = []
    for page_id, patches in sorted(page_to_patches.items()):
        unique_patch_ids = sorted({
            patch["patch_id"]
            for patch in patches
            if isinstance(patch.get("patch_id"), str)
        })
        if len(unique_patch_ids) < 2:
            continue

        digest = hashlib.sha256(f"{page_id}:{','.join(unique_patch_ids)}".encode("utf-8")).hexdigest()
        conflict_id = f"conflict-{digest[:12]}"
        detected_at = max(
            float(patch.get("created_at", 0.0))
            for patch in patches
            if isinstance(patch.get("created_at"), (int, float))
        )
        conflict_status = "resolved" if conflict_id in resolutions else "pending"
        if status != "all" and conflict_status != status:
            continue
        conflicts.append(
            {
                "conflict_id": conflict_id,
                "type": "page_overlap",
                "detected_at": detected_at,
                "patches": unique_patch_ids,
                "pages": [page_id],
                "status": conflict_status,
            }
        )

    return {"status": "success", "conflicts": conflicts, "total": len(conflicts)}


def wiki_resolve_conflict(
    wiki_root: str,
    conflict_id: str,
    action: str,
    resolver: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Resolve a pending conflict and persist an audit record.
    """
    conflicts_result = wiki_list_conflicts(wiki_root, status="all")
    if conflicts_result.get("status") != "success":
        return conflicts_result

    conflict = None
    for item in conflicts_result.get("conflicts", []):
        if item.get("conflict_id") == conflict_id:
            conflict = item
            break
    if conflict is None:
        return {
            "status": "failed",
            "reason": "conflict_not_found",
            "message": f"Conflict '{conflict_id}' not found",
        }

    root = Path(wiki_root)
    audit_dir = root / ".audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    resolution_file = audit_dir / "conflict_resolutions.jsonl"
    record = {
        "conflict_id": conflict_id,
        "action": action,
        "resolver": resolver,
        "reason": reason,
        "resolved_at": time.time(),
        "status": "resolved",
    }
    with resolution_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "status": "success",
        "change_id": _generate_change_id(),
        "resolution": action,
        "conflict_id": conflict_id,
    }


def wiki_lint(wiki_root: str, scope: str = "all") -> Dict[str, Any]:
    """
    Run wiki lint checks.
    """
    if scope not in {"all", "pending", "recent"}:
        return {
            "status": "failed",
            "reason": "invalid_scope",
            "message": "scope must be one of: all, pending, recent",
        }

    root = Path(wiki_root)
    wiki_dir = root / "wiki"
    paths: List[Path] = []

    if scope == "all":
        paths = sorted(wiki_dir.rglob("*.md")) if wiki_dir.exists() else []
    elif scope == "pending":
        for patch in _load_pending_patch_records(root):
            for page_id in patch.get("affected_pages", []):
                if not isinstance(page_id, str):
                    continue
                existing = _resolve_existing_page_path(root, page_id)
                if existing and existing not in paths:
                    paths.append(existing)
    else:
        try:
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD", "--", "wiki"],
                cwd=wiki_root,
                capture_output=True,
                text=True,
                check=True,
            )
            for line in diff_result.stdout.splitlines():
                path = (root / line.strip()).resolve()
                if path.suffix == ".md" and path.exists():
                    paths.append(path)
        except subprocess.CalledProcessError:
            paths = sorted(wiki_dir.rglob("*.md")) if wiki_dir.exists() else []

    linter = WikiLinter()
    lint_result = linter.lint_paths([str(p) for p in paths])
    errors = []
    warnings = []
    for issue in lint_result.issues:
        issue_dict = {
            "code": issue.code,
            "file": issue.file,
            "message": issue.message,
        }
        if issue.severity == "error":
            errors.append(issue_dict)
        else:
            warnings.append(issue_dict)

    check_map = {
        "frontmatter_validation": {"missing_frontmatter", "invalid_frontmatter"},
        "required_fields": {"missing_required_field"},
        "confidence_range": {"invalid_confidence"},
        "source_refs": {"missing_source_refs"},
        "duplicate_page_id": {"duplicate_page_id"},
        "dead_link_check": {"broken_wikilink"},
    }
    error_codes = {issue["code"] for issue in errors}
    checks = [
        {"name": check_name, "passed": len(codes & error_codes) == 0}
        for check_name, codes in check_map.items()
    ]

    return {
        "status": "passed" if lint_result.passed else "failed",
        "scope": scope,
        "checked_files": [str(p) for p in paths],
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "errors_count": lint_result.errors_count,
        "warnings_count": lint_result.warnings_count,
    }


def wiki_rollback(
    wiki_root: str,
    change_id: str,
    approved_by: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Roll back an applied change by reverting its git commit.
    """
    acl = ApprovalACL(f"{wiki_root}/.schema/approvers.yaml")
    if not acl.verify_approver(approved_by):
        return {
            "status": "failed",
            "reason": "unauthorized_approver",
            "message": f"Approver '{approved_by}' is not authorized",
        }
    if not acl.check_permission(approved_by, "rollback"):
        return {
            "status": "failed",
            "reason": "insufficient_permission",
            "message": f"Approver '{approved_by}' cannot approve 'rollback'",
        }

    commit_lookup = subprocess.run(
        ["git", "log", "--all", "--grep", f"Change ID: {change_id}", "--format=%H", "-n", "1"],
        cwd=wiki_root,
        capture_output=True,
        text=True,
        check=False,
    )
    target_commit = commit_lookup.stdout.strip()
    if not target_commit:
        return {
            "status": "failed",
            "reason": "change_not_found",
            "message": f"Change '{change_id}' was not found in git history",
        }

    revert_result = subprocess.run(
        ["git", "revert", "--no-edit", target_commit],
        cwd=wiki_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if revert_result.returncode != 0:
        return {
            "status": "failed",
            "reason": "rollback_failed",
            "message": revert_result.stderr.strip() or "git revert failed",
        }

    new_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wiki_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    root = Path(wiki_root)
    audit_dir = root / ".audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    rollback_log = audit_dir / "rollbacks.jsonl"
    rollback_change_id = _generate_change_id()
    record = {
        "rollback_change_id": rollback_change_id,
        "original_change_id": change_id,
        "target_commit": target_commit,
        "rollback_commit": new_commit,
        "approved_by": approved_by,
        "reason": reason,
        "rolled_back_at": time.time(),
    }
    with rollback_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "status": "success",
        "rollback_change_id": rollback_change_id,
        "original_change_id": change_id,
        "rolled_back_at": record["rolled_back_at"],
    }
