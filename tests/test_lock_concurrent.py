"""
Additional test for concurrent renew/release vs takeover race condition
"""

import os
import time
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from wiki_engine.lock_manager import LockManager, Lease


def test_concurrent_renew_vs_takeover():
    """
    Test that renew and takeover don't race.

    Scenario:
    1. Thread A holds a lease and tries to renew it
    2. Thread B tries to take over an expired lease
    3. Verify: no state corruption, operations are serialized
    """
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # Thread A acquires lease with short duration
        lease_a = lock_manager.acquire_lease(
            resource_id=resource_id,
            request_id="request-a",
            agent_id="agent-a",
            duration=0.2  # 200ms
        )

        assert lease_a is not None

        # Wait for near-expiration
        time.sleep(0.15)

        # Concurrent operations:
        # Thread A tries to renew
        # Thread B tries to take over (will wait for expiration)
        def renew_operation():
            time.sleep(0.01)  # Small delay
            return lock_manager.renew_lease(lease_a)

        def takeover_operation():
            time.sleep(0.1)  # Wait for expiration
            return lock_manager.acquire_lease(
                resource_id=resource_id,
                request_id="request-b",
                agent_id="agent-b",
                duration=30.0
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_renew = executor.submit(renew_operation)
            future_takeover = executor.submit(takeover_operation)

            renew_result = future_renew.result()
            takeover_result = future_takeover.result()

        # Verify: either renew succeeded (and takeover failed)
        # or renew failed (expired) and takeover succeeded
        # But not both succeeded or both failed
        if renew_result:
            # Renew succeeded, takeover should fail
            assert takeover_result is None, "Takeover should fail if renew succeeded"
        else:
            # Renew failed (expired), takeover should succeed
            assert takeover_result is not None, "Takeover should succeed if renew failed"

        print("✓ test_concurrent_renew_vs_takeover passed")

    finally:
        shutil.rmtree(wiki_root)


def test_concurrent_release_vs_takeover():
    """
    Test that release and takeover don't race.

    Scenario:
    1. Thread A holds a lease and tries to release it
    2. Thread B tries to take over
    3. Verify: no double-success, operations are serialized
    """
    wiki_root = tempfile.mkdtemp()

    try:
        lock_manager = LockManager(wiki_root)
        resource_id = "test-resource"

        # Thread A acquires lease
        lease_a = lock_manager.acquire_lease(
            resource_id=resource_id,
            request_id="request-a",
            agent_id="agent-a",
            duration=30.0
        )

        assert lease_a is not None

        # Concurrent operations:
        # Thread A releases
        # Thread B tries to acquire
        def release_operation():
            lock_manager.release_lease(lease_a)

        def acquire_operation():
            time.sleep(0.01)  # Small delay
            return lock_manager.acquire_lease(
                resource_id=resource_id,
                request_id="request-b",
                agent_id="agent-b",
                duration=30.0
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_release = executor.submit(release_operation)
            future_acquire = executor.submit(acquire_operation)

            future_release.result()
            acquire_result = future_acquire.result()

        # After release, acquire should succeed
        assert acquire_result is not None, "Acquire should succeed after release"
        assert acquire_result.request_id == "request-b"

        print("✓ test_concurrent_release_vs_takeover passed")

    finally:
        shutil.rmtree(wiki_root)


if __name__ == "__main__":
    test_concurrent_renew_vs_takeover()
    test_concurrent_release_vs_takeover()
    print("\n✓ All concurrent operation tests passed")
