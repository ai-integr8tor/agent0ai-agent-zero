"""
Open Notebook Plugin - Ephemeral Telemetry

In-memory operation metrics for MVP validation period.
Data is discarded when the agent session ends.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _TelemetryStore:
    """In-memory telemetry store. One instance per process."""
    total_ops: int = 0
    success_ops: int = 0
    failure_ops: int = 0
    total_latency_ms: float = 0.0
    tool_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.monotonic)
    unhealthy_since: float | None = None


# Module-level singleton
_store = _TelemetryStore()


def record_operation(tool_name: str, success: bool, latency_ms: float) -> None:
    """Record a tool operation outcome."""
    _store.total_ops += 1
    if success:
        _store.success_ops += 1
    else:
        _store.failure_ops += 1
    _store.total_latency_ms += latency_ms
    # Track just the method part (e.g., 'browse:notebooks')
    _store.tool_counts[tool_name] += 1


def set_unhealthy(unhealthy: bool) -> None:
    """Track when connection became unhealthy."""
    if unhealthy and _store.unhealthy_since is None:
        _store.unhealthy_since = time.monotonic()
    elif not unhealthy:
        _store.unhealthy_since = None


def get_unhealthy_duration_minutes() -> float | None:
    """Get minutes since connection became unhealthy, or None."""
    if _store.unhealthy_since is None:
        return None
    return (time.monotonic() - _store.unhealthy_since) / 60.0


def get_summary() -> str:
    """Get a formatted telemetry summary."""
    if _store.total_ops == 0:
        return "No operations recorded yet."

    success_rate = (_store.success_ops / _store.total_ops) * 100
    avg_latency = _store.total_latency_ms / _store.total_ops

    lines = [
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Operations | {_store.total_ops} |",
        f"| Success Rate | {success_rate:.1f}% |",
        f"| Avg Latency | {avg_latency:.0f}ms |",
    ]

    if _store.tool_counts:
        top_tools = sorted(_store.tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        tools_str = ", ".join(f"{name} ({count})" for name, count in top_tools)
        lines.append(f"| Most Used | {tools_str} |")

    return "\n".join(lines)


def reset() -> None:
    """Reset telemetry (for testing)."""
    global _store
    _store = _TelemetryStore()
