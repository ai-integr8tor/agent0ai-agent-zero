"""Async stdio JSON transport for ACP foundation work."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from helpers.acp.debug_log import DebugLog
from helpers.acp.errors import AcpProcessExitedError, AcpProtocolError, AcpTimeoutError, AcpTransportError


class StdioTransport:
    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        debug_log: DebugLog | None = None,
        startup_timeout: float = 10.0,
        operation_timeout: float = 30.0,
        close_timeout: float = 5.0,
        max_line_bytes: int = 1_048_576,
        stderr_max_line_bytes: int = 64_000,
    ):
        if isinstance(argv, str) or not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise AcpTransportError("argv must be a non-empty list of strings")
        if cwd is not None:
            cwd_path = Path(cwd).expanduser().resolve()
            if not cwd_path.is_dir():
                raise AcpTransportError("cwd does not exist or is not a directory")
            self.cwd: str | None = str(cwd_path)
        else:
            self.cwd = None
        self.argv = argv
        self.env = self._controlled_env(env)
        self.debug_log = debug_log or DebugLog()
        self.startup_timeout = startup_timeout
        self.operation_timeout = operation_timeout
        self.close_timeout = close_timeout
        self.max_line_bytes = max_line_bytes
        self.stderr_max_line_bytes = stderr_max_line_bytes
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._closed = False
        self._unhealthy: BaseException | None = None

    async def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *self.argv,
                    cwd=self.cwd,
                    env=self.env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=self.startup_timeout,
            )
        except TimeoutError as exc:
            raise AcpTimeoutError("timed out starting ACP child process") from exc
        except Exception as exc:
            raise AcpTransportError("failed to start ACP child process") from exc
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def send_json(self, obj: dict[str, Any]) -> None:
        self._ensure_healthy()
        process = self._require_process()
        self.debug_log.outbound(obj)
        if process.stdin is None or process.returncode is not None:
            self._mark_unhealthy(AcpProcessExitedError("ACP child process is not running"))
            raise self._unhealthy
        try:
            payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            process.stdin.write(payload)
            await asyncio.wait_for(process.stdin.drain(), timeout=self.operation_timeout)
        except TimeoutError as exc:
            self._mark_unhealthy(AcpTimeoutError("timed out writing to ACP child process"))
            raise self._unhealthy from exc
        except (TypeError, ValueError) as exc:
            raise AcpProtocolError("object is not JSON serializable") from exc
        except Exception as exc:
            self._mark_unhealthy(AcpProcessExitedError("ACP child process write failed"))
            raise self._unhealthy from exc

    async def read_json(self) -> dict[str, Any]:
        self._ensure_healthy()
        process = self._require_process()
        if process.stdout is None:
            raise AcpTransportError("stdout pipe is unavailable")
        if process.returncode is not None:
            self._mark_unhealthy(AcpProcessExitedError("ACP child process exited"))
            raise self._unhealthy
        try:
            line = await asyncio.wait_for(self._read_bounded_line(process.stdout), timeout=self.operation_timeout)
        except TimeoutError as exc:
            raise AcpTimeoutError("timed out reading from ACP child process") from exc
        if line == b"":
            await self._poll_returncode()
            self._mark_unhealthy(AcpProcessExitedError("ACP child process exited"))
            raise self._unhealthy
        try:
            obj = json.loads(line.decode("utf-8"))
        except Exception as exc:
            self._mark_unhealthy(AcpProtocolError("malformed JSON on ACP stdout"))
            raise self._unhealthy from exc
        if not isinstance(obj, dict):
            self._mark_unhealthy(AcpProtocolError("ACP stdout JSON must be an object"))
            raise self._unhealthy
        self.debug_log.inbound(obj)
        return obj

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(process.wait(), timeout=self.close_timeout)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=min(1.0, self.close_timeout))
                except TimeoutError:
                    process.kill()
                    await process.wait()
        await self._cancel_stderr_task()

    async def kill(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        self._closed = True
        await self._cancel_stderr_task()

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None and not self._closed

    def returncode(self) -> int | None:
        return None if self._process is None else self._process.returncode

    def diagnostics(self) -> list[dict[str, Any]]:
        return self.debug_log.snapshot()

    async def _read_bounded_line(self, stream: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await stream.read(1)
            if chunk == b"":
                return b"" if total == 0 else b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > self.max_line_bytes:
                self._mark_unhealthy(AcpProtocolError("ACP stdout line exceeded maximum size"))
                raise self._unhealthy
            if chunk == b"\n":
                return b"".join(chunks)

    async def _stderr_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            text = line[: self.stderr_max_line_bytes].decode("utf-8", errors="replace").rstrip("\n")
            self.debug_log.stderr(text)

    async def _cancel_stderr_task(self) -> None:
        task = self._stderr_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._stderr_task = None

    async def _poll_returncode(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=0.1)
            except TimeoutError:
                pass

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise AcpTransportError("ACP child process has not been started")
        return self._process

    def _ensure_healthy(self) -> None:
        if self._closed:
            raise AcpTransportError("ACP transport is closed")
        if self._unhealthy is not None:
            raise AcpTransportError(str(self._unhealthy)) from self._unhealthy

    def _mark_unhealthy(self, exc: BaseException) -> None:
        self._unhealthy = exc

    @staticmethod
    def _controlled_env(env: dict[str, str] | None) -> dict[str, str]:
        base = {key: value for key, value in os.environ.items() if key in {"PATH", "PYTHONPATH", "HOME", "LANG", "LC_ALL"}}
        if env:
            base.update({str(key): str(value) for key, value in env.items()})
        return base
