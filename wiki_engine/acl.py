"""
Wiki ACL - Approval Access Control with anti-replay signatures

Provides:
- HMAC-based approval signatures
- Nonce + TTL for replay prevention
- Atomic nonce check and consumption (flock protected)
- Permission-based access control
"""

import os
import json
import time
import hmac
import hashlib
import secrets
import fcntl
import yaml
from typing import Optional, Dict, List, Tuple


class ApprovalACL:
    """
    Approval access control with anti-replay signatures.

    Key features:
    - HMAC signatures with nonce and TTL
    - Atomic nonce check+consume (no replay window)
    - Permission-based operation authorization
    """

    def __init__(self, config_path: str, secret_key: Optional[str] = None):
        self.config_path = config_path
        self.config = self._load_config()
        self.secret_key = secret_key or self._load_secret_key()
        self.signature_ttl = self.config['signature']['ttl_seconds']

        audit_dir = self.config['audit']['audit_dir']
        self.used_nonces_file = f"{audit_dir}/used_nonces.jsonl"
        self.nonce_lock_file = f"{audit_dir}/.nonce.lock"

        self._ensure_audit_dir()

    def _load_config(self) -> dict:
        """Load approvers configuration"""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _load_secret_key(self) -> str:
        """Load or generate secret key"""
        # In production, load from secure storage
        # For now, use a fixed key (should be replaced)
        return "wiki-secret-key-change-in-production"

    def _ensure_audit_dir(self):
        """Ensure audit directory exists"""
        audit_dir = self.config['audit']['audit_dir']
        os.makedirs(audit_dir, exist_ok=True)

    def sign_approval(self, approver_id: str, patch_id: str,
                     expected_base_commit: str) -> dict:
        """
        Generate approval signature with nonce and TTL.

        Args:
            approver_id: ID of the approver
            patch_id: ID of the patch being approved
            expected_base_commit: Expected base commit hash

        Returns:
            Signed approval dict with all required fields
        """
        # Generate random nonce (128 bits)
        nonce = secrets.token_hex(16)

        timestamp = time.time()
        expires_at = timestamp + self.signature_ttl

        # Construct message (includes expected_base_commit per @codex requirement)
        message = f"{approver_id}:{patch_id}:{timestamp}:{nonce}:{expires_at}:{expected_base_commit}"

        # Generate HMAC signature
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            "approver_id": approver_id,
            "patch_id": patch_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "expires_at": expires_at,
            "expected_base_commit": expected_base_commit,
            "signature": signature
        }

    def verify_signature(self, signed_approval: dict) -> Tuple[bool, str]:
        """
        Verify approval signature with atomic nonce check+consume.

        This is the critical anti-replay mechanism:
        1. Acquire nonce lock
        2. Check if nonce is used
        3. Verify signature
        4. Mark nonce as used
        5. Release lock

        All steps happen atomically under flock protection.

        Returns:
            (valid, reason)
        """
        # 1. Check required fields
        required_fields = ["approver_id", "patch_id", "timestamp", "nonce",
                          "expires_at", "expected_base_commit", "signature"]
        if not all(f in signed_approval for f in required_fields):
            return (False, "missing_required_fields")

        # 2. Check expiration
        if time.time() > signed_approval["expires_at"]:
            return (False, "signature_expired")

        # 3. Atomic nonce check + consume (flock protected)
        with open(self.nonce_lock_file, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

            try:
                # Check if nonce is already used
                if self._is_nonce_used(signed_approval["nonce"]):
                    return (False, "nonce_already_used")

                # Verify HMAC signature
                message = f"{signed_approval['approver_id']}:{signed_approval['patch_id']}:{signed_approval['timestamp']}:{signed_approval['nonce']}:{signed_approval['expires_at']}:{signed_approval['expected_base_commit']}"

                expected_signature = hmac.new(
                    self.secret_key.encode(),
                    message.encode(),
                    hashlib.sha256
                ).hexdigest()

                if not hmac.compare_digest(signed_approval["signature"], expected_signature):
                    return (False, "invalid_signature")

                # Mark nonce as used (still under lock)
                self._mark_nonce_used(signed_approval["nonce"], signed_approval["expires_at"])

                return (True, "valid")

            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def verify_approver(self, approver_id: str,
                       auth_token: Optional[str] = None) -> bool:
        """Verify approver identity"""
        approver = self._get_approver(approver_id)
        if not approver:
            return False

        # Check authentication method
        if approver["auth_method"] == "session_identity":
            # Session-based auth (handled by upper layer)
            return True

        elif approver["auth_method"] == "api_key":
            # API key verification (constant-time comparison)
            if not auth_token:
                return False

            token_hash = f"sha256:{hashlib.sha256(auth_token.encode()).hexdigest()}"
            return hmac.compare_digest(token_hash, approver["api_key_hash"])

        return False

    def check_permission(self, approver_id: str, operation: str) -> bool:
        """Check if approver has permission for operation"""
        approver = self._get_approver(approver_id)
        if not approver:
            return False

        # Check permissions
        for perm in approver["permissions"]:
            allowed_ops = self.config["operation_permissions"].get(perm, [])
            if "*" in allowed_ops or operation in allowed_ops:
                return True

        return False

    def _get_approver(self, approver_id: str) -> Optional[dict]:
        """Get approver configuration"""
        for approver in self.config["authorized_approvers"]:
            if approver["id"] == approver_id:
                return approver
        return None

    def _is_nonce_used(self, nonce: str) -> bool:
        """Check if nonce has been used (must be called under lock)"""
        current_time = time.time()

        try:
            with open(self.used_nonces_file, 'r') as f:
                for line in f:
                    record = json.loads(line)
                    # Only check non-expired nonces
                    if record["expires_at"] > current_time:
                        if record["nonce"] == nonce:
                            return True
        except FileNotFoundError:
            pass

        return False

    def _mark_nonce_used(self, nonce: str, expires_at: float):
        """Mark nonce as used (must be called under lock)"""
        record = {
            "nonce": nonce,
            "used_at": time.time(),
            "expires_at": expires_at
        }

        # Append to log
        with open(self.used_nonces_file, 'a') as f:
            f.write(json.dumps(record) + '\n')

    def cleanup_expired_nonces(self):
        """Clean up expired nonces (periodic maintenance task)"""
        current_time = time.time()
        valid_records = []

        try:
            with open(self.used_nonces_file, 'r') as f:
                for line in f:
                    record = json.loads(line)
                    if record["expires_at"] > current_time:
                        valid_records.append(record)

            # Rewrite file with only valid records
            with open(self.used_nonces_file, 'w') as f:
                for record in valid_records:
                    f.write(json.dumps(record) + '\n')

        except FileNotFoundError:
            pass
