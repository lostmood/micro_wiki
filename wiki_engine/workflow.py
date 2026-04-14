"""
Wiki Workflow Engine - propose -> lint -> apply pipeline

Implements the three-stage workflow:
1. propose_patch: Generate patch_id, write to .pending/, run lint
2. apply_patch: Verify signature, check TOCTOU, apply atomically
3. Audit trail: All operations logged with change_id

Key features:
- TOCTOU protection (expected_base_commit validation)
- Atomic apply with lease protection
- Signature verification (patch_id must match)
- Lint gate before apply
"""

import os
import json
import time
import uuid
import hashlib
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path

from wiki_engine.lock_manager import LockManager
from wiki_engine.acl import ApprovalACL
from wiki_engine.lint import WikiLinter


@dataclass
class Patch:
    """Patch record for proposed changes"""
    patch_id: str
    request_id: str
    agent_id: str
    operation: str  # "create" / "update" / "delete"
    affected_pages: List[str]
    diff_content: str
    confidence: float
    source_refs: List[str]
    base_commit: str
    created_at: float
    lint_status: Optional[str] = None
    lint_errors: Optional[List[Dict]] = None


class WikiWorkflow:
    """
    Wiki workflow engine with three-stage pipeline.

    Workflow:
    1. propose_patch -> generates patch_id, writes to .pending/, runs lint
    2. apply_patch -> verifies signature, checks TOCTOU, applies atomically
    3. Audit trail -> logs all operations with change_id
    """

    def __init__(self, wiki_root: str):
        self.wiki_root = wiki_root
        self.pending_dir = f"{wiki_root}/.pending"
        self.audit_dir = f"{wiki_root}/.audit"

        self.lock_manager = LockManager(wiki_root)
        self.acl = ApprovalACL(f"{wiki_root}/.schema/approvers.yaml")
        self.linter = WikiLinter()

        self._ensure_dirs()

    def _ensure_dirs(self):
        """Ensure required directories exist"""
        os.makedirs(self.pending_dir, exist_ok=True)
        os.makedirs(self.audit_dir, exist_ok=True)

    def propose_patch(self, agent_id: str, operation: str,
                     pages: List[str], diff: str,
                     confidence: float, sources: List[str]) -> Dict[str, Any]:
        """
        Propose a patch (Stage 1: propose).

        Args:
            agent_id: ID of the agent proposing the patch
            operation: Operation type ("create" / "update" / "delete")
            pages: List of affected page IDs
            diff: Unified diff of changes
            confidence: Agent's confidence score (0.0-1.0)
            sources: List of source references

        Returns:
            {
                "status": "success",
                "patch_id": "patch-...",
                "requires_approval": true,
                "confidence": 0.95,
                "lint_status": "passed" / "failed"
            }
        """
        # Generate unique patch_id and request_id
        patch_id = self._generate_patch_id()
        request_id = f"{agent_id}-{uuid.uuid4().hex[:8]}"

        # Get current base commit
        base_commit = self._get_current_commit()

        # Create patch object
        patch = Patch(
            patch_id=patch_id,
            request_id=request_id,
            agent_id=agent_id,
            operation=operation,
            affected_pages=pages,
            diff_content=diff,
            confidence=confidence,
            source_refs=sources,
            base_commit=base_commit,
            created_at=time.time()
        )

        # Run lint checks
        lint_result = self._run_lint(patch)

        patch.lint_status = "passed" if lint_result.passed else "failed"
        if not lint_result.passed:
            patch.lint_errors = [
                {
                    "code": issue.code,
                    "file": issue.file,
                    "message": issue.message
                }
                for issue in lint_result.issues if issue.severity == "error"
            ]

        # Save to .pending/
        self._save_patch(patch)

        return {
            "status": "success",
            "patch_id": patch_id,
            "requires_approval": True,  # v1: always requires approval
            "confidence": confidence,
            "lint_status": patch.lint_status,
            "lint_errors": patch.lint_errors if patch.lint_errors else None
        }

    def apply_patch(self, patch_id: str, signed_approval: Dict[str, Any],
                   expected_base_commit: str) -> Dict[str, Any]:
        """
        Apply a patch (Stage 2: apply).

        Args:
            patch_id: ID of the patch to apply
            signed_approval: Signed approval dict with all required fields
            expected_base_commit: Expected base commit hash

        Returns:
            {
                "status": "success",
                "change_id": "ch-...",
                "commit_hash": "abc123...",
                "applied_at": 1234567890.123
            }
        """
        # 1. Load patch
        patch = self._load_patch(patch_id)
        if not patch:
            return {
                "status": "failed",
                "reason": "patch_not_found",
                "message": f"Patch '{patch_id}' not found in .pending/"
            }

        # 2. Verify lint passed
        if patch.lint_status != "passed":
            return {
                "status": "failed",
                "reason": "lint_failed",
                "message": "Patch did not pass lint checks",
                "errors": patch.lint_errors
            }

        # 3. Verify signature (with anti-replay)
        valid, reason = self.acl.verify_signature(signed_approval)
        if not valid:
            return {
                "status": "failed",
                "reason": f"signature_verification_failed: {reason}",
                "message": "Invalid or expired approval signature"
            }

        approver_id = signed_approval["approver_id"]

        # 4. Critical: Verify patch_id matches (prevent signature reuse across patches)
        if signed_approval["patch_id"] != patch_id:
            return {
                "status": "failed",
                "reason": "patch_id_mismatch",
                "message": f"Signature is for patch '{signed_approval['patch_id']}', not '{patch_id}'"
            }

        # 5. Verify approver identity
        if not self.acl.verify_approver(approver_id):
            return {
                "status": "failed",
                "reason": "unauthorized_approver",
                "message": f"Approver '{approver_id}' is not authorized"
            }

        # 6. Check permission
        if not self.acl.check_permission(approver_id, patch.operation):
            return {
                "status": "failed",
                "reason": "insufficient_permission",
                "message": f"Approver '{approver_id}' cannot approve '{patch.operation}'"
            }

        # 7. TOCTOU protection: verify expected_base_commit matches current
        current_commit = self._get_current_commit()
        if current_commit != expected_base_commit:
            return {
                "status": "failed",
                "reason": "base_commit_changed",
                "message": "Base commit has changed since patch was proposed",
                "expected": expected_base_commit,
                "actual": current_commit
            }

        # 8. Verify signature's expected_base_commit matches
        if signed_approval["expected_base_commit"] != expected_base_commit:
            return {
                "status": "failed",
                "reason": "signature_base_commit_mismatch",
                "message": "Signature's expected_base_commit does not match provided value"
            }

        # 9. Acquire leases for affected pages
        leases = []
        for page in patch.affected_pages:
            lease = self.lock_manager.acquire_lease(
                resource_id=page,
                request_id=patch.request_id,
                agent_id=patch.agent_id,
                duration=60.0
            )
            if not lease:
                # Release already acquired leases
                for l in leases:
                    self.lock_manager.release_lease(l)
                return {
                    "status": "failed",
                    "reason": "lock_acquisition_failed",
                    "message": f"Could not acquire lock for page '{page}'"
                }
            leases.append(lease)

        try:
            # 10. Re-check TOCTOU (double-check under lock)
            current_commit = self._get_current_commit()
            if current_commit != expected_base_commit:
                return {
                    "status": "failed",
                    "reason": "base_commit_changed",
                    "message": "Base commit changed during lock acquisition"
                }

            # 11. Apply changes (placeholder - actual implementation in later phases)
            # For now, just simulate successful apply
            change_id = self._generate_change_id()

            # 12. Record audit log
            self._append_to_audit_log(patch, approver_id, change_id, signed_approval)

            # 13. Git commit (placeholder)
            commit_hash = self._git_commit(patch, approver_id, change_id)

            # 14. Cleanup .pending/
            self._cleanup_patch(patch_id)

            return {
                "status": "success",
                "change_id": change_id,
                "commit_hash": commit_hash,
                "applied_at": time.time()
            }

        finally:
            # 15. Release all leases
            for lease in leases:
                self.lock_manager.release_lease(lease)

    def _generate_patch_id(self) -> str:
        """Generate unique patch ID"""
        timestamp = int(time.time() * 1000)
        random_suffix = uuid.uuid4().hex[:8]
        return f"patch-{timestamp}-{random_suffix}"

    def _generate_change_id(self) -> str:
        """Generate unique change ID"""
        timestamp = int(time.time() * 1000)
        random_suffix = uuid.uuid4().hex[:8]
        return f"ch-{timestamp}-{random_suffix}"

    def _get_current_commit(self) -> str:
        """Get current git commit hash"""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.wiki_root,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            # If not a git repo or no commits, return placeholder
            return "initial"

    def _run_lint(self, patch: Patch) -> Any:
        """Run lint checks on patch (placeholder)"""
        # For now, return a passing result
        # In real implementation, would extract files from diff and lint them
        from wiki_engine.lint import LintResult
        return LintResult(passed=True, issues=[], errors_count=0, warnings_count=0)

    def _save_patch(self, patch: Patch):
        """Save patch to .pending/"""
        patch_file = f"{self.pending_dir}/{patch.patch_id}.json"
        with open(patch_file, 'w') as f:
            json.dump(asdict(patch), f, indent=2)

    def _load_patch(self, patch_id: str) -> Optional[Patch]:
        """Load patch from .pending/"""
        patch_file = f"{self.pending_dir}/{patch_id}.json"
        try:
            with open(patch_file, 'r') as f:
                data = json.load(f)
                return Patch(**data)
        except FileNotFoundError:
            return None

    def _cleanup_patch(self, patch_id: str):
        """Remove patch from .pending/"""
        patch_file = f"{self.pending_dir}/{patch_id}.json"
        try:
            os.remove(patch_file)
        except FileNotFoundError:
            pass

    def _append_to_audit_log(self, patch: Patch, approver_id: str,
                            change_id: str, signed_approval: Dict):
        """Append to audit log"""
        log_file = f"{self.audit_dir}/changes.jsonl"

        record = {
            "change_id": change_id,
            "patch_id": patch.patch_id,
            "agent_id": patch.agent_id,
            "approver_id": approver_id,
            "operation": patch.operation,
            "affected_pages": patch.affected_pages,
            "confidence": patch.confidence,
            "source_refs": patch.source_refs,
            "base_commit": patch.base_commit,
            "applied_at": time.time(),
            "approval_signature": signed_approval
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(record) + '\n')

    def _git_commit(self, patch: Patch, approver_id: str, change_id: str) -> str:
        """Create git commit (placeholder)"""
        # For now, return a placeholder hash
        # In real implementation, would create actual git commit
        return hashlib.sha1(change_id.encode()).hexdigest()[:7]
