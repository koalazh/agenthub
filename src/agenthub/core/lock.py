"""Cross-platform file lock for Git operations."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows


class GitLock:
    """Git operation file lock with cross-platform support.

    Uses fcntl on Unix and file existence check on Windows.
    """

    def __init__(self, lock_path: Path, timeout: float = 30.0) -> None:
        """Initialize the lock.

        Args:
            lock_path: Path to the lock file
            timeout: Maximum time to wait for lock acquisition in seconds
        """
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Acquire the lock.

        Returns:
            True if lock was acquired, False if timeout
        """
        start = time.time()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                if _HAS_FCNTL:
                    # Unix: Use fcntl for proper file locking
                    self._fd = os.open(
                        str(self.lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    )
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    # Windows: Use file existence as lock
                    # Create lock file exclusively - fails if it exists
                    self._fd = os.open(
                        str(self.lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    )
                return True
            except FileExistsError:
                if time.time() - start > self.timeout:
                    return False
                time.sleep(0.1)

    def release(self) -> None:
        """Release the lock."""
        if self._fd is not None:
            if _HAS_FCNTL:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            else:
                os.close(self._fd)
            self._fd = None
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    @contextmanager
    def hold(self) -> "Generator[None, None, None]":
        """Context manager for lock acquisition.

        Yields:
            None

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        if not self.acquire():
            raise TimeoutError(f"Failed to acquire lock: {self.lock_path}")
        try:
            yield
        finally:
            self.release()
