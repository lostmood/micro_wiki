"""
Tests for ACL - Anti-replay signature verification

Verifies:
1. Signature replay prevention (nonce already used)
2. Signature expiration
3. Atomic nonce check+consume
"""

import os
import time
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from wiki_engine.acl import ApprovalACL


def test_signature_replay_prevention():
    """
    Test that signatures cannot be replayed.

    Scenario:
    1. Generate and use a signature once
    2. Try to use the same signature again
    3. Verify: second use fails with nonce_already_used
    """
    # Setup temp config
    wiki_root = tempfile.mkdtemp()
    config_path = f"{wiki_root}/.schema/approvers.yaml"

    try:
        # Create minimal config
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)

        with open(config_path, 'w') as f:
            f.write("""
version: "v1"
signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
authorized_approvers:
  - id: "test-approver"
    permissions: ["approve_all"]
operation_permissions:
  approve_all: ["*"]
audit:
  audit_dir: ".audit"
""")

        acl = ApprovalACL(config_path, secret_key="test-secret")

        # Generate signature
        signed_approval = acl.sign_approval(
            approver_id="test-approver",
            patch_id="patch-001",
            expected_base_commit="abc123"
        )

        # First use: should succeed
        valid1, reason1 = acl.verify_signature(signed_approval)
        assert valid1, f"First use should succeed, got: {reason1}"
        assert reason1 == "valid"

        # Second use: should fail (replay)
        valid2, reason2 = acl.verify_signature(signed_approval)
        assert not valid2, "Second use should fail"
        assert reason2 == "nonce_already_used", f"Expected nonce_already_used, got: {reason2}"

        print("✓ test_signature_replay_prevention passed")

    finally:
        shutil.rmtree(wiki_root)


def test_signature_expiration():
    """Test that expired signatures are rejected"""
    wiki_root = tempfile.mkdtemp()
    config_path = f"{wiki_root}/.schema/approvers.yaml"

    try:
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)

        with open(config_path, 'w') as f:
            f.write("""
version: "v1"
signature:
  ttl_seconds: 1
  nonce_bits: 128
  algorithm: "hmac_sha256"
authorized_approvers:
  - id: "test-approver"
    permissions: ["approve_all"]
operation_permissions:
  approve_all: ["*"]
audit:
  audit_dir: ".audit"
""")

        acl = ApprovalACL(config_path, secret_key="test-secret")

        # Generate signature with 1 second TTL
        signed_approval = acl.sign_approval(
            approver_id="test-approver",
            patch_id="patch-001",
            expected_base_commit="abc123"
        )

        # Wait for expiration
        time.sleep(1.5)

        # Should fail due to expiration
        valid, reason = acl.verify_signature(signed_approval)
        assert not valid, "Expired signature should fail"
        assert reason == "signature_expired", f"Expected signature_expired, got: {reason}"

        print("✓ test_signature_expiration passed")

    finally:
        shutil.rmtree(wiki_root)


def test_concurrent_replay_attempts():
    """
    Test that concurrent replay attempts are all rejected.

    Scenario:
    1. Generate one signature
    2. 10 concurrent threads try to use it
    3. Verify: exactly 1 succeeds, 9 fail with nonce_already_used
    """
    wiki_root = tempfile.mkdtemp()
    config_path = f"{wiki_root}/.schema/approvers.yaml"

    try:
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)

        with open(config_path, 'w') as f:
            f.write("""
version: "v1"
signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
authorized_approvers:
  - id: "test-approver"
    permissions: ["approve_all"]
operation_permissions:
  approve_all: ["*"]
audit:
  audit_dir: ".audit"
""")

        acl = ApprovalACL(config_path, secret_key="test-secret")

        # Generate one signature
        signed_approval = acl.sign_approval(
            approver_id="test-approver",
            patch_id="patch-001",
            expected_base_commit="abc123"
        )

        # 10 concurrent verification attempts
        def try_verify(i):
            return acl.verify_signature(signed_approval)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(try_verify, i) for i in range(10)]
            results = [f.result() for f in futures]

        # Count successes and failures
        successes = [(valid, reason) for valid, reason in results if valid]
        failures = [(valid, reason) for valid, reason in results if not valid]

        # Verify: exactly 1 success
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(failures) == 9, f"Expected 9 failures, got {len(failures)}"

        # All failures should be nonce_already_used
        for valid, reason in failures:
            assert reason == "nonce_already_used", f"Expected nonce_already_used, got: {reason}"

        print("✓ test_concurrent_replay_attempts passed")

    finally:
        shutil.rmtree(wiki_root)


def test_invalid_signature():
    """Test that tampered signatures are rejected"""
    wiki_root = tempfile.mkdtemp()
    config_path = f"{wiki_root}/.schema/approvers.yaml"

    try:
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)

        with open(config_path, 'w') as f:
            f.write("""
version: "v1"
signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
authorized_approvers:
  - id: "test-approver"
    permissions: ["approve_all"]
operation_permissions:
  approve_all: ["*"]
audit:
  audit_dir: ".audit"
""")

        acl = ApprovalACL(config_path, secret_key="test-secret")

        # Generate signature
        signed_approval = acl.sign_approval(
            approver_id="test-approver",
            patch_id="patch-001",
            expected_base_commit="abc123"
        )

        # Tamper with patch_id
        signed_approval["patch_id"] = "patch-002"

        # Should fail due to invalid signature
        valid, reason = acl.verify_signature(signed_approval)
        assert not valid, "Tampered signature should fail"
        assert reason == "invalid_signature", f"Expected invalid_signature, got: {reason}"

        print("✓ test_invalid_signature passed")

    finally:
        shutil.rmtree(wiki_root)


def test_permission_check():
    """Test permission-based access control"""
    wiki_root = tempfile.mkdtemp()
    config_path = f"{wiki_root}/.schema/approvers.yaml"

    try:
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)

        with open(config_path, 'w') as f:
            f.write("""
version: "v1"
signature:
  ttl_seconds: 300
authorized_approvers:
  - id: "admin"
    permissions: ["approve_all"]
  - id: "reviewer"
    permissions: ["approve_low_risk"]
operation_permissions:
  approve_all: ["*"]
  approve_low_risk: ["create_page", "add_link"]
audit:
  audit_dir: ".audit"
""")

        acl = ApprovalACL(config_path, secret_key="test-secret")

        # Admin can approve anything
        assert acl.check_permission("admin", "delete_page")
        assert acl.check_permission("admin", "create_page")

        # Reviewer can only approve low-risk operations
        assert acl.check_permission("reviewer", "create_page")
        assert acl.check_permission("reviewer", "add_link")
        assert not acl.check_permission("reviewer", "delete_page")

        print("✓ test_permission_check passed")

    finally:
        shutil.rmtree(wiki_root)


if __name__ == "__main__":
    test_signature_replay_prevention()
    test_signature_expiration()
    test_concurrent_replay_attempts()
    test_invalid_signature()
    test_permission_check()
    print("\n✓ All ACL tests passed")
