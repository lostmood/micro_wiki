"""
Wiki Lock Manager - Lease + Fencing Token with flock-protected CAS takeover

Provides atomic lease acquisition with:
- Fencing tokens for ordering
- flock-protected CAS takeover for expired leases
- Prevents double-success in concurrent takeover scenarios
"""

import os
import json
import time
import uuid
import fcntl
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Lease:
    """Lease record with fencing token"""
    resource_id: str
    request_id: str  # Unique per operation (not per agent)
    agent_id: str    # For audit trail
    fencing_token: int
    acquired_at: float
    expires_at: float
    lease_duration: float = 30.0


class LockManager:
    """
    Lock manager with atomic lease acquisition and flock-protected takeover.

    Key guarantees:
    - Only one lease holder per resource at any time
    - Expired leases can be taken over atomically
    - No double-success in concurrent takeover scenarios
    """

    def __init__(self, wiki_root: str):
        self.wiki_root = wiki_root
        self.lock_dir = f"{wiki_root}/.locks"
        self.token_counter_file = f"{self.lock_dir}/token_counter"
        self.global_lock_file = f"{self.lock_dir}/.global.lock"
        self._ensure_lock_dir()

    def _ensure_lock_dir(self):
        """Ensure lock directory exists"""
        os.makedirs(self.lock_dir, exist_ok=True)

        # Initialize token counter if not exists
        if not os.path.exists(self.token_counter_file):
            with open(self.token_counter_file, 'w') as f:
                f.write('0')

    def acquire_lease(self, resource_id: str, request_id: str, agent_id: str,
                     duration: float = 30.0) -> Optional[Lease]:
        """
        Acquire lease atomically.

        Returns:
            Lease object if successful, None if resource is locked
        """
        lock_file = f"{self.lock_dir}/{resource_id}.lease"
        temp_file = f"{self.lock_dir}/.tmp-{request_id}"

        # Generate fencing token
        fencing_token = self._next_fencing_token()

        # Create lease object
        lease = Lease(
            resource_id=resource_id,
            request_id=request_id,
            agent_id=agent_id,
            fencing_token=fencing_token,
            acquired_at=time.time(),
            expires_at=time.time() + duration,
            lease_duration=duration
        )

        # Write to temp file
        with open(temp_file, 'w') as f:
            json.dump(asdict(lease), f)

        try:
            # Try atomic creation via hard link
            os.link(temp_file, lock_file)
            os.remove(temp_file)
            return lease

        except FileExistsError:
            # Lock file exists, try CAS takeover if expired
            return self._cas_takeover_with_flock(lock_file, temp_file, lease)

    def _cas_takeover_with_flock(self, lock_file: str, temp_file: str,
                                 new_lease: Lease) -> Optional[Lease]:
        """
        CAS takeover with flock protection (default implementation).

        Uses global lock to ensure atomic check-and-replace of expired leases.
        """
        try:
            # Acquire global lock for CAS operation
            with open(self.global_lock_file, 'w') as global_lock:
                fcntl.flock(global_lock.fileno(), fcntl.LOCK_EX)

                try:
                    # Read existing lease
                    existing_lease = self._read_lease(lock_file)

                    # Check if expired
                    if not existing_lease or time.time() < existing_lease.expires_at:
                        # Not expired, acquisition fails
                        os.remove(temp_file)
                        return None

                    # Expired, perform atomic replacement
                    os.rename(temp_file, lock_file)

                    # Log takeover for audit
                    self._log_lease_takeover(existing_lease, new_lease)

                    return new_lease

                finally:
                    fcntl.flock(global_lock.fileno(), fcntl.LOCK_UN)

        except OSError:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return None

    def renew_lease(self, lease: Lease) -> bool:
        """Renew an existing lease (flock protected)"""
        lock_file = f"{self.lock_dir}/{lease.resource_id}.lease"

        # Use global lock to prevent race with takeover
        with open(self.global_lock_file, 'w') as global_lock:
            fcntl.flock(global_lock.fileno(), fcntl.LOCK_EX)

            try:
                # Check current holder
                current_lease = self._read_lease(lock_file)
                if not current_lease or current_lease.request_id != lease.request_id:
                    return False

                # Update expiration
                lease.expires_at = time.time() + lease.lease_duration

                with open(lock_file, 'w') as f:
                    json.dump(asdict(lease), f)

                return True

            finally:
                fcntl.flock(global_lock.fileno(), fcntl.LOCK_UN)

    def release_lease(self, lease: Lease):
        """Release a lease (flock protected)"""
        lock_file = f"{self.lock_dir}/{lease.resource_id}.lease"

        # Use global lock to prevent race with takeover
        with open(self.global_lock_file, 'w') as global_lock:
            fcntl.flock(global_lock.fileno(), fcntl.LOCK_EX)

            try:
                # Only holder can release
                current_lease = self._read_lease(lock_file)
                if current_lease and current_lease.request_id == lease.request_id:
                    try:
                        os.remove(lock_file)
                    except FileNotFoundError:
                        pass

            finally:
                fcntl.flock(global_lock.fileno(), fcntl.LOCK_UN)

    def validate_fencing_token(self, resource_id: str, token: int) -> bool:
        """Validate fencing token to prevent stale operations"""
        lock_file = f"{self.lock_dir}/{resource_id}.lease"
        current_lease = self._read_lease(lock_file)

        if not current_lease:
            return False

        # Token must match and lease must be valid
        return (current_lease.fencing_token == token and
                time.time() < current_lease.expires_at)

    def _next_fencing_token(self) -> int:
        """Generate monotonically increasing fencing token"""
        with open(self.token_counter_file, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                counter = int(f.read().strip() or "0")
                counter += 1
                f.seek(0)
                f.write(str(counter))
                f.truncate()
                return counter
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _read_lease(self, lock_file: str) -> Optional[Lease]:
        """Read lease from file"""
        try:
            with open(lock_file, 'r') as f:
                data = json.load(f)
                return Lease(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _log_lease_takeover(self, old_lease: Lease, new_lease: Lease):
        """Log lease takeover for audit"""
        log_file = f"{self.lock_dir}/takeover.log"

        log_entry = {
            "timestamp": time.time(),
            "resource_id": new_lease.resource_id,
            "old_holder": {
                "request_id": old_lease.request_id,
                "agent_id": old_lease.agent_id,
                "fencing_token": old_lease.fencing_token,
                "expired_at": old_lease.expires_at
            },
            "new_holder": {
                "request_id": new_lease.request_id,
                "agent_id": new_lease.agent_id,
                "fencing_token": new_lease.fencing_token
            }
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
