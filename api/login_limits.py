"""Failed-login throttling for POST /api/auth/login.

Counts failed attempts per username and per client IP over a sliding
window; once either reaches its limit, logins from it are refused (429)
until the oldest failure in the window ages out. A successful login clears
that username's count but not the IP's, so an attacker with an account of
their own can't reset the IP limit by signing in between guesses.

Deliberate trade-off: anyone who knows a username can keep that account
locked out with a few wrong passwords per window. For a small app with a
handful of known users, that's preferred over leaving guesses unthrottled.

Kept in memory: the app runs as one process (fly.toml), and a restart
clearing the counts is acceptable for a 15-minute window.
"""

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_USERNAME = 5
# Higher than per-username: several people may sign in from one address.
MAX_FAILURES_PER_IP = 20
# Bounds memory under a flood of distinct usernames / addresses.
_MAX_KEYS = 10_000


class LoginLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._failures: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, ip: Optional[str]):
        keys = [(f"user:{username.strip().lower()}", MAX_FAILURES_PER_USERNAME)]
        if ip:
            keys.append((f"ip:{ip}", MAX_FAILURES_PER_IP))
        return keys

    def _recent(self, key: str, now: float) -> Deque[float]:
        times = self._failures.get(key)
        if times is None:
            return deque()
        while times and now - times[0] >= WINDOW_SECONDS:
            times.popleft()
        if not times:
            del self._failures[key]
        return times

    def retry_after(self, username: str, ip: Optional[str]) -> int:
        """Seconds until a login may be tried again, or 0 if it may now."""
        now = self._clock()
        wait = 0.0
        with self._lock:
            for key, limit in self._keys(username, ip):
                times = self._recent(key, now)
                if len(times) >= limit:
                    wait = max(wait, WINDOW_SECONDS - (now - times[-limit]))
        return int(wait) + 1 if wait > 0 else 0

    def record_failure(self, username: str, ip: Optional[str]) -> None:
        now = self._clock()
        with self._lock:
            if len(self._failures) >= _MAX_KEYS:
                for key in list(self._failures):
                    self._recent(key, now)
                if len(self._failures) >= _MAX_KEYS:
                    self._failures.clear()
            for key, _ in self._keys(username, ip):
                self._failures.setdefault(key, deque()).append(now)

    def record_success(self, username: str) -> None:
        with self._lock:
            self._failures.pop(self._keys(username, None)[0][0], None)


limiter = LoginLimiter()
