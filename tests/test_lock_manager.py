"""
Tests for Lock Manager - CAS takeover atomicity

Verifies:
1. No double-success in concurrent takeover scenarios
2. Expired lease recovery
3. Fencing token validation
"""

import os
import time
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from wiki_engine.lock_manager import LockManager, Lease


def test_cas_takeover_no_double_success():
    """
    Test that concurrent takeover of expired lease results in only one success.

    Scenario:
    1. Create an expired lease
    2. 10 concurrent requests try to take it over
    3. Verify: exactly 1 succeeds, 9 fail
    """
    # Setup temp wiki root
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # Create an expired lease manually (use token=0 so new tokens will be > 0)
        lock_file = f"{wiki_root}/.locks/{resource_id}.lease"
        expired_lease = Lease(
            resource_id=resource_id,
            request_id="expired-request",
            agent_id="expired-agent",
            fencing_token=0,
            acquired_at=time.time() - 100,
            expires_at=time.time() - 50,  # Expired 50 seconds ago
            lease_duration=30.0
        )

        import json
        from dataclasses import asdict
        with open(lock_file, 'w') as f:
            json.dump(asdict(expired_lease), f)

        # 10 concurrent takeover attempts
        def try_acquire(i):
            return lock_manager.acquire_lease(
                resource_id=resource_id,
                request_id=f"request-{i}",
                agent_id=f"agent-{i}",
                duration=30.0
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(try_acquire, i) for i in range(10)]
            results = [f.result() for f in futures]

        # Count successes
        successes = [r for r in results if r is not None]
        failures = [r for r in results if r is None]

        # Verify: exactly 1 success
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(failures) == 9, f"Expected 9 failures, got {len(failures)}"

        # Verify the winner has a valid lease
        winner = successes[0]
        assert winner.resource_id == resource_id
        assert winner.fencing_token > expired_lease.fencing_token

        print("✓ test_cas_takeover_no_double_success passed")

    finally:
        shutil.rmtree(wiki_root)


def test_expired_lease_recovery():
    """Test that expired leases can be recovered"""
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # Acquire lease with short duration
        lease1 = lock_manager.acquire_lease(
            resource_id=resource_id,
            request_id="request-1",
            agent_id="agent-1",
            duration=0.1  # 100ms
        )

        assert lease1 is not None

        # Wait for expiration
        time.sleep(0.2)

        # Another request should succeed (takeover)
        lease2 = lock_manager.acquire_lease(
            resource_id=resource_id,
            request_id="request-2",
            agent_id="agent-2",
            duration=30.0
        )

        assert lease2 is not None
        assert lease2.request_id == "request-2"
        assert lease2.fencing_token > lease1.fencing_token

        print("✓ test_expired_lease_recovery passed")

    finally:
        shutil.rmtree(wiki_root)


def test_fencing_token_validation():
    """Test fencing token prevents stale operations"""
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # Acquire lease
        lease1 = lock_manager.acquire_lease(
            resource_id=resource_id,
            request_id="request-1",
            agent_id="agent-1",
            duration=30.0
        )

        # Valid token should pass
        assert lock_manager.validate_fencing_token(resource_id, lease1.fencing_token)

        # Invalid token should fail
        assert not lock_manager.validate_fencing_token(resource_id, lease1.fencing_token + 1)
        assert not lock_manager.validate_fencing_token(resource_id, lease1.fencing_token - 1)

        # Release and token should fail
        lock_manager.release_lease(lease1)
        assert not lock_manager.validate_fencing_token(resource_id, lease1.fencing_token)

        print("✓ test_fencing_token_validation passed")

    finally:
        shutil.rmtree(wiki_root)


def test_concurrent_acquisition_same_resource():
    """Test that concurrent acquisition of same resource results in only one success"""
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # 10 concurrent acquisition attempts
        def try_acquire(i):
            return lock_manager.acquire_lease(
                resource_id=resource_id,
                request_id=f"request-{i}",
                agent_id=f"agent-{i}",
                duration=30.0
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(try_acquire, i) for i in range(10)]
            results = [f.result() for f in futures]

        # Count successes
        successes = [r for r in results if r is not None]

        # Verify: exactly 1 success
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"

        print("✓ test_concurrent_acquisition_same_resource passed")

    finally:
        shutil.rmtree(wiki_root)


if __name__ == "__main__":
    test_cas_takeover_no_double_success()
    test_expired_lease_recovery()
    test_fencing_token_validation()
    test_concurrent_acquisition_same_resource()
    print("\n✓ All lock manager tests passed")
