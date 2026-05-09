from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Literal, cast

from watchdog.observers import Observer as _WatchdogObserver

from helpers.exclusion import get_noise_folders


class _DispatchHandler:
    def __init__(self, registry: "_WatchRegistry", scheduled_root: str):
        self.registry = registry
        self.scheduled_root = scheduled_root

    def dispatch(self, event: Any):
        self.registry.dispatch(self.scheduled_root, event)


WatchEvent = Literal["create", "modify", "delete", "move"]
WatchEvents = Literal["all"] | list[WatchEvent | str] | set[WatchEvent | str]
WatchItem = list[str]
WatchHandler = Callable[[list[WatchItem]], None]
PatternMatcher = Callable[[str], bool]

_DEFAULT_PATTERNS = ["**/*"]
_DEFAULT_IGNORE_PATTERNS = [
    "**/*.pyc",
    "**/*.pyo",
]
_VALID_EVENTS: frozenset[WatchEvent] = frozenset(["create", "modify", "delete", "move"])
_EVENT_ALIASES: dict[str, WatchEvent] = {
    "create": "create",
    "created": "create",
    "modify": "modify",
    "modified": "modify",
    "delete": "delete",
    "deleted": "delete",
    "move": "move",
    "moved": "move",
}


def _iter_watchable_dirs(root: str) -> list[str]:
    excluded = get_noise_folders()
    result = [root]
    for dirpath, dirnames, _ in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in excluded]
        result.extend(os.path.join(dirpath, d) for d in dirnames)
    return result


@dataclass(frozen=True)
class _Watch:
    id: str
    root: str
    root_with_sep: str
    patterns: list[str]
    ignore_patterns: list[str]
    matcher: PatternMatcher
    events: frozenset[WatchEvent]
    debounce: float
    handler: WatchHandler


@dataclass
class _PendingBatch:
    items_by_path: dict[str, WatchItem]
    timer: threading.Timer | None = None


class _WatchRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._observer: Any = None
        self._watches: dict[str, _Watch] = {}
        self._watch_ids_by_group: dict[str, set[str]] = {}
        self._scheduled_roots: set[str] = set()
        self._pending_batches: dict[str, _PendingBatch] = {}
        self._batching: bool = False

    def add(
        self,
        id: str,
        roots: list[str],
        patterns: list[str] | None,
        ignore_patterns: list[str] | None,
        events: WatchEvents,
        debounce: float,
        handler: WatchHandler,
    ) -> None:
        self._ensure_watchdog_available()
        normalized_roots = [r for r in _normalize_roots(roots) if not _is_9p_mount(r)]
        normalized_patterns = _normalize_patterns(patterns)
        normalized_ignore_patterns = _normalize_patterns(
            ignore_patterns, default=_DEFAULT_IGNORE_PATTERNS
        )
        normalized_events = _normalize_events(events)
        normalized_debounce = _normalize_debounce(debounce)
        watch_ids = [id] if len(normalized_roots) == 1 else [f"{id}:{index}" for index in range(len(normalized_roots))]
        watches = {
            watch_id: _Watch(
                id=watch_id,
                root=normalized_root,
                root_with_sep=normalized_root + os.sep,
                patterns=normalized_patterns,
                ignore_patterns=normalized_ignore_patterns,
                matcher=_compile_matcher(
                    normalized_root,
                    normalized_patterns,
                    normalized_ignore_patterns,
                ),
                events=normalized_events,
                debounce=normalized_debounce,
                handler=handler,
            )
            for watch_id, normalized_root in zip(watch_ids, normalized_roots)
        }
        with self._lock:
            previous_watch_ids = self._watch_ids_by_group.pop(id, set())
            for watch_id in previous_watch_ids:
                self._watches.pop(watch_id, None)
                pending = self._pending_batches.pop(watch_id, None)
                if pending and pending.timer:
                    pending.timer.cancel()
            self._watches.update(watches)
            self._watch_ids_by_group[id] = set(watches)
            if not self._batching:
                self._refresh_observer()

    def remove(self, id: str) -> bool:
        with self._lock:
            watch_ids = self._watch_ids_by_group.pop(id, {id})
            removed = False
            for watch_id in watch_ids:
                removed = self._watches.pop(watch_id, None) is not None or removed
                pending = self._pending_batches.pop(watch_id, None)
                if pending and pending.timer:
                    pending.timer.cancel()
            if removed and not self._batching:
                self._refresh_observer()
            return removed

    def clear(self) -> None:
        with self._lock:
            self._watches.clear()
            self._watch_ids_by_group.clear()
            pending_batches = list(self._pending_batches.values())
            self._pending_batches.clear()
            if not self._batching:
                self._refresh_observer()
        for pending in pending_batches:
            if pending.timer:
                pending.timer.cancel()

    def start(self) -> None:
        with self._lock:
            observer = self._observer
            if observer is None:
                observer = self._create_observer()
                self._observer = observer
            if observer.is_alive():
                return
            observer.start()

    def stop(self) -> None:
        self._stop_observer()

    def dispatch(self, scheduled_root: str, event: Any) -> None:
        event_type = _map_event_type(str(getattr(event, "event_type", "")))
        if event_type is None:
            return
        if bool(getattr(event, "is_synthetic", False)):
            return
        paths: list[str] = []
        src_path = getattr(event, "src_path", None)
        if isinstance(src_path, str) and src_path:
            paths.append(os.path.abspath(src_path))
        dest_path = getattr(event, "dest_path", None)
        if event_type == "move" and isinstance(dest_path, str) and dest_path:
            paths.append(os.path.abspath(dest_path))
        with self._lock:
            watches = list(self._watches.values())
        for path in paths:
            if not _is_same_or_nested(path, scheduled_root):
                continue
            for watch in watches:
                if event_type not in watch.events:
                    continue
                if not _is_under_watch(path, watch):
                    continue
                if not watch.matcher(path):
                    continue
                self._queue_event(watch, path, event_type)
        if event_type in ("create", "move") and bool(getattr(event, "is_directory", False)):
            src_path = getattr(event, "src_path", None)
            if isinstance(src_path, str) and os.path.basename(src_path) not in get_noise_folders():
                threading.Thread(target=self._refresh_observer, daemon=True).start()

    def _ensure_watchdog_available(self) -> None:
        return None

    def _queue_event(self, watch: _Watch, path: str, event_type: WatchEvent) -> None:
        item: WatchItem = [path, event_type]
        if watch.debounce <= 0:
            watch.handler([item])
            return
        with self._lock:
            pending = self._pending_batches.get(watch.id)
            if pending is None:
                pending = _PendingBatch(items_by_path={})
                self._pending_batches[watch.id] = pending
            pending.items_by_path[path] = item
            timer = pending.timer
            if timer:
                timer.cancel()
            pending.timer = threading.Timer(watch.debounce, self._flush_watch_batch, args=(watch.id,))
            pending.timer.daemon = True
            pending.timer.start()

    def _flush_watch_batch(self, watch_id: str) -> None:
        items: list[WatchItem] = []
        handler: WatchHandler | None = None
        with self._lock:
            watch = self._watches.get(watch_id)
            pending = self._pending_batches.pop(watch_id, None)
            if watch is None or pending is None:
                return
            if pending.timer:
                pending.timer.cancel()
            items = list(pending.items_by_path.values())
            handler = watch.handler
        if items:
            handler(items)

    def _refresh_observer(self) -> None:
        target_roots = _covering_roots(watch.root for watch in self._watches.values())
        if not target_roots:
            self._stop_observer()
            return
        observer = self._observer
        if observer is None:
            observer = self._create_observer()
            self._observer = observer
            observer.start()
        dir_set = set(d for root in target_roots for d in _iter_watchable_dirs(root))
        if dir_set == self._scheduled_roots:
            return
        observer = cast(Any, observer)
        observer.unschedule_all()
        for dir_path in dir_set:
            observer.schedule(_DispatchHandler(self, dir_path), dir_path, recursive=False)
        self._scheduled_roots = dir_set

    def _stop_observer(self) -> None:
        with self._lock:
            observer = self._observer
            self._observer = None
            self._scheduled_roots = set()
        if observer is None:
            return
        observer.unschedule_all()
        observer.stop()
        observer.join()

    def _create_observer(self) -> Any:
        observer = cast(Any, _WatchdogObserver())
        return observer

    @contextmanager
    def batch(self):
        self._batching = True
        try:
            yield
        finally:
            self._batching = False
            self._refresh_observer()


def _normalize_root(root: str) -> str:
    normalized = os.path.abspath(os.path.normpath(root))
    if not os.path.exists(normalized):
        os.makedirs(normalized, exist_ok=True)
    if not os.path.isdir(normalized):
        raise NotADirectoryError(normalized)
    return normalized


def _normalize_roots(roots: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(_normalize_root(item) for item in roots))
    if not normalized:
        raise ValueError("roots must not be empty")
    return normalized


def _normalize_patterns(
    patterns: list[str] | None,
    default: list[str] | None = None,
) -> list[str]:
    default = default or _DEFAULT_PATTERNS
    if not patterns:
        return list(default)
    normalized = [pattern.strip().replace("\\", "/") for pattern in patterns if pattern and pattern.strip()]
    return normalized or default


def _normalize_events(events: WatchEvents) -> frozenset[WatchEvent]:
    if events == "all":
        return _VALID_EVENTS
    normalized: set[WatchEvent] = set()
    for event in events:
        mapped = _map_event_type(str(event))
        if mapped is None:
            raise ValueError(f"Unsupported watch event: {event}")
        normalized.add(mapped)
    return frozenset(normalized) if normalized else _VALID_EVENTS


def _map_event_type(event_type: str) -> WatchEvent | None:
    return _EVENT_ALIASES.get(event_type.lower())


def _normalize_debounce(debounce: float) -> float:
    if debounce < 0:
        raise ValueError("debounce must be >= 0")
    return debounce


def _covering_roots(roots: Iterable[str]) -> set[str]:
    ordered = sorted(set(roots), key=lambda root: (len(root), root))
    covered: set[str] = set()
    for root in ordered:
        if any(_is_same_or_nested(root, parent) for parent in covered):
            continue
        covered.add(root)
    return covered


def _is_9p_mount(path: str) -> bool:
    """
    Check if path resides on a 9p remote filesystem
    Related: https://github.com/microsoft/WSL/issues/4739
    """
    path = os.path.realpath(path)
    best = ""
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mountpoint, fstype = parts[1], parts[2]
                if fstype != "9p":
                    continue
                real_mp = os.path.realpath(mountpoint)
                if path.startswith(real_mp + os.sep) or path == real_mp:
                    if len(real_mp) > len(best):
                        best = real_mp
    except OSError:
        return False
    return bool(best)


def _is_same_or_nested(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _is_under_watch(path: str, watch: _Watch) -> bool:
    return path == watch.root or path.startswith(watch.root_with_sep)


def _compile_matcher(
    root: str,
    patterns: list[str],
    ignore_patterns: list[str],
) -> PatternMatcher:
    include_matcher = _compile_single_matcher(root, patterns)
    ignore_matcher = _compile_single_matcher(root, ignore_patterns)

    def matches(path: str) -> bool:
        return include_matcher(path) and not ignore_matcher(path)

    return matches


def _compile_single_matcher(root: str, patterns: list[str]) -> PatternMatcher:
    if not patterns or patterns == _DEFAULT_PATTERNS:
        return lambda path: True

    if any(pattern in {"**", "**/*", "*"} for pattern in patterns):
        return lambda path: True

    relative_patterns = [pattern for pattern in patterns if "/" in pattern]
    name_patterns = [
        pattern for pattern in patterns if "/" not in pattern and pattern not in {"**", "**/*", "*"}
    ]

    def matches(path: str) -> bool:
        relative = os.path.relpath(path, root).replace("\\", "/")
        if relative == ".":
            relative = ""
        relative_path = PurePosixPath(relative) if relative else PurePosixPath("")
        name_path = PurePosixPath(os.path.basename(path))

        for pattern in relative_patterns:
            if relative and relative_path.match(pattern):
                return True
        for pattern in name_patterns:
            if name_path.match(pattern):
                return True
            if relative and relative_path.match(pattern):
                return True
        return False

    return matches


_registry = _WatchRegistry()
_registry.start()


def add_watchdog(
    id: str,
    roots: list[str],
    patterns: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
    events: WatchEvents = "all",
    debounce: float = 0.01,
    handler: WatchHandler | None = None,
) -> None:
    if handler is None:
        raise ValueError("handler is required")
    _registry.add(
        id=id,
        roots=roots,
        patterns=patterns,
        ignore_patterns=ignore_patterns,
        events=events,
        debounce=debounce,
        handler=handler,
    )


def remove_watchdog(id: str) -> bool:
    return _registry.remove(id)


def clear_watchdogs() -> None:
    _registry.clear()


def batch_watchdogs():
    return _registry.batch()


def start_watchdog_daemon() -> None:
    _registry.start()


def stop_watchdog_daemon() -> None:
    _registry.stop()


__all__ = [
    "WatchEvent",
    "WatchEvents",
    "WatchItem",
    "WatchHandler",
    "add_watchdog",
    "remove_watchdog",
    "clear_watchdogs",
    "batch_watchdogs",
    "start_watchdog_daemon",
    "stop_watchdog_daemon",
]

