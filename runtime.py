"""Runner exclusivity, interruptible scheduling and bounded retry policy."""
import os
import math
from pathlib import Path
import random
import signal
import threading
import time


class RunnerLock:
    """OS-held advisory lock, automatically released on process death."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.file = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.file.write(b'0')
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError('another runner is using this application directory') from exc
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()
            self.file = None
        # Never unlink: a new inode would permit two independent locks.


class Stop:
    def __init__(self):
        self.event = threading.Event()
        self.handlers = {}

    def __enter__(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.handlers[sig] = signal.signal(sig, self.request)
        return self

    def request(self, *_):
        self.event.set()

    def __exit__(self, *args):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)

    def wait(self, seconds):
        return self.event.wait(max(0, seconds))

    def stopped(self):
        return self.event.is_set()


class RetryClock:
    """Map persisted UTC retry timestamps to this run's monotonic timeline."""
    def __init__(self):
        self.wall = time.time()
        self.mono = time.monotonic()

    def now(self):
        return self.wall + time.monotonic() - self.mono


def backoff(attempt, base, cap, retry_after=0):
    ceiling = min(cap, base * 2 ** min(max(attempt - 1, 0), 30))
    # Equal jitter avoids immediate hot-loop retries.
    return max(random.uniform(ceiling / 2, ceiling), max(0, retry_after))


def retry_after(exchange, cap):
    """Honor numeric or HTTP-date Retry-After, without retrying earlier than the server allows."""
    from email.utils import parsedate_to_datetime
    headers = getattr(exchange, 'last_response_headers', None)
    if not isinstance(headers, dict):
        return 0
    value = next((v for k, v in headers.items() if k.lower() == 'retry-after'), None)
    try:
        seconds = float(value)
        return max(0, seconds) if math.isfinite(seconds) else 0
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 0


def resumed(previous_wall, previous_mono, grace):
    wall_delta = time.time() - previous_wall
    mono_delta = time.monotonic() - previous_mono
    return wall_delta - mono_delta > grace or wall_delta < -grace
