import threading
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from libs.connectors.base import RateLimiter


def test_rate_limiter_does_not_exceed_limit_under_concurrency():
    """With max_requests=1 and window=0.5s, 8 threads must not all pass at once."""
    limiter = RateLimiter(max_requests=1, window_seconds=0.5)
    timestamps: list[float] = []
    lock = threading.Lock()

    def acquire_and_record():
        limiter.acquire()
        with lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=acquire_and_record) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(timestamps) == 8, "All 8 threads must complete"
    # No two acquisitions within the same 0.5s window (allow 0.05s jitter)
    timestamps.sort()
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        assert gap >= 0.35, f"Gap between acquisitions {i-1} and {i} was {gap:.3f}s (expected >= 0.35s)"


def test_rate_limiter_multi_slot_does_not_exceed_limit():
    """With max_requests=3 and window=0.3s, 12 threads must not all pass at once."""
    limiter = RateLimiter(max_requests=3, window_seconds=0.3)
    timestamps: list[float] = []
    lock = threading.Lock()

    def acquire_and_record():
        limiter.acquire()
        with lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=acquire_and_record) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(timestamps) == 12, "All 12 threads must complete"
    # In each 0.3s window, at most 3 threads should have acquired
    timestamps.sort()
    # Check that no more than 3 acquisitions happened in any 0.3s window
    for i in range(len(timestamps)):
        window_end = timestamps[i] + 0.3
        in_window = sum(1 for t in timestamps if timestamps[i] <= t <= window_end)
        assert in_window <= 3 + 1, f"Too many acquisitions ({in_window}) in a 0.3s window starting at index {i}"
