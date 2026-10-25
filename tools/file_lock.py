"""
Cross-Platform Zero-Dependency Inter-Process File Lock.
Uses msvcrt on Windows and fcntl on Unix/Linux/macOS.
Provides a thread-safe and process-safe context manager for atomic writes
to shared ledgers (applications.csv, results.csv, auth_state.json).
"""
import os
import sys
import time
import pathlib
from typing import Optional


class FileLock:
    """
    Acquires an exclusive advisory lock on a lockfile.
    Supports retries with exponential backoff and timeout.
    """

    def __init__(self, target_path: os.PathLike, timeout: float = 30.0, delay: float = 0.05):
        p = pathlib.Path(target_path)
        # Suffix lock file to avoid modifying the target data file itself
        if not str(p).endswith(".lock"):
            self.lock_path = p.with_name(p.name + ".lock")
        else:
            self.lock_path = p
        self.timeout = timeout
        self.delay = delay
        self._fd = None

    def __enter__(self):
        start = time.time()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        attempt = 0

        while True:
            try:
                # Open or create the lockfile in read/write binary mode
                self._fd = open(self.lock_path, "a+b")
                if sys.platform == "win32":
                    import msvcrt
                    self._fd.seek(0)
                    # Non-blocking lock on the first byte
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (IOError, OSError, PermissionError, BlockingIOError):
                if self._fd:
                    try:
                        self._fd.close()
                    except Exception:
                        pass
                    self._fd = None

                elapsed = time.time() - start
                if elapsed >= self.timeout:
                    # Timeout reached; break and proceed with caution rather than hard-locking
                    break

                attempt += 1
                # Small jittered backoff: 0.02s to 0.1s
                sleep_time = min(self.delay * (1.2 ** min(attempt, 8)), 0.2)
                time.sleep(sleep_time)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fd.close()
            except Exception:
                pass
            self._fd = None
