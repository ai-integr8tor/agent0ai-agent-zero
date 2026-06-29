"""Bounded masked debug logging for ACP transports and peers."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DebugRecord:
    timestamp: str
    direction: str
    kind: str
    method: str | None
    id: str | int | None
    preview: str


class DebugLog:
    def __init__(
        self,
        max_records: int = 2000,
        max_preview_chars: int = 4000,
        masker: Callable[[str], str] | None = None,
    ):
        self.max_preview_chars = max(0, int(max_preview_chars))
        self.masker = masker
        self._records: deque[DebugRecord] = deque(maxlen=max(1, int(max_records)))

    def record(
        self,
        *,
        direction: str,
        kind: str,
        payload: Any = None,
        method: str | None = None,
        id: str | int | None = None,
    ) -> None:
        try:
            preview = self._preview(payload)
        except Exception:
            preview = "<preview unavailable>"
        self._records.append(
            DebugRecord(
                timestamp=datetime.now(UTC).isoformat(),
                direction=direction,
                kind=kind,
                method=method,
                id=id,
                preview=preview,
            )
        )

    def inbound(self, payload: Any) -> None:
        self.record(direction="inbound", kind=self._kind(payload), payload=payload, method=self._method(payload), id=self._id(payload))

    def outbound(self, payload: Any) -> None:
        self.record(direction="outbound", kind=self._kind(payload), payload=payload, method=self._method(payload), id=self._id(payload))

    def stderr(self, text: str) -> None:
        self.record(direction="stderr", kind="stderr", payload=text)

    def system(self, message: str, *, kind: str = "system") -> None:
        self.record(direction="system", kind=kind, payload=message)

    def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self._records]

    def clear(self) -> None:
        self._records.clear()

    def _preview(self, payload: Any) -> str:
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        if self.masker is not None:
            text = self.masker(text)
        return text[: self.max_preview_chars]

    @staticmethod
    def _method(payload: Any) -> str | None:
        return payload.get("method") if isinstance(payload, dict) and isinstance(payload.get("method"), str) else None

    @staticmethod
    def _id(payload: Any) -> str | int | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("id")
        return value if isinstance(value, str | int) else None

    @staticmethod
    def _kind(payload: Any) -> str:
        if isinstance(payload, dict):
            if "method" in payload and "id" in payload:
                return "request"
            if "method" in payload:
                return "notification"
            if "error" in payload:
                return "error"
            if "result" in payload:
                return "response"
        return "system"
