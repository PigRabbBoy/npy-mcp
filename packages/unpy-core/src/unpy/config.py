"""Runtime configuration knobs for unpy (v2.0.0 performance suite).

All knobs are environment variables read lazily so tests can monkeypatch
os.environ at call time. ``UNPY_LEGACY=1`` is the single escape hatch that
reverts every v2 behavior change (TTL cache, write batching, threaded
fan-out) to the v1.x behavior in one switch.
"""

import os

DEFAULT_BATCH_MAX_OPS = 100
DEFAULT_CACHE_TTL_SECONDS = 15.0
DEFAULT_MAX_WORKERS = 8


def legacy_mode() -> bool:
    """True when UNPY_LEGACY=1 — v1.x behavior across the board."""
    return os.environ.get("UNPY_LEGACY") == "1"


def batch_max_ops() -> int:
    """Hard cap on operations per saveTransactionsFanout batch."""
    if legacy_mode():
        return 0  # 0 disables batching entirely (one tx per call, v1 style)
    raw = os.environ.get("UNPY_BATCH_MAX_OPS")
    try:
        val = int(raw) if raw else DEFAULT_BATCH_MAX_OPS
    except ValueError:
        val = DEFAULT_BATCH_MAX_OPS
    return max(1, val)


def cache_ttl_seconds() -> float:
    """RecordStore freshness window; 0 disables the TTL cache."""
    if legacy_mode():
        return 0.0
    raw = os.environ.get("UNPY_CACHE_TTL")
    try:
        return max(0.0, float(raw)) if raw else DEFAULT_CACHE_TTL_SECONDS
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def machine_worker_default() -> int:
    """Auto worker count from the machine: min(8, max(2, cores - 2))."""
    try:
        cores = os.cpu_count() or 2
    except Exception:
        cores = 2
    return min(8, max(2, cores - 2))


def max_workers() -> int:
    """Fan-out thread pool size (machine-aware, capped at 8, env-overridable)."""
    if legacy_mode():
        return 1
    raw = os.environ.get("UNPY_MAX_WORKERS")
    try:
        val = int(raw) if raw else machine_worker_default()
    except ValueError:
        val = machine_worker_default()
    return max(1, min(8, val))