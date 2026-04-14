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
import yaml

from wiki_engine.workflow import WikiWorkflow


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
