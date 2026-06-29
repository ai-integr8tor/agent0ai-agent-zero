"""Protocol-agnostic JSON-RPC 2.0 peer for ACP foundation work."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from helpers.acp.debug_log import DebugLog
from helpers.acp.errors import AcpJsonRpcError, AcpProtocolError, AcpTimeoutError, AcpTransportError
from helpers.acp.transport import StdioTransport

Handler = Callable[[Any], Awaitable[Any] | Any]


class JsonRpcPeer:
    def __init__(self, transport: StdioTransport, *, debug_log: DebugLog | None = None, request_timeout: float = 30.0):
        self.transport = transport
        self.debug_log = debug_log or transport.debug_log
        self.request_timeout = request_timeout
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future] = {}
        self._request_handlers: dict[str, Handler] = {}
        self._notification_handlers: dict[str, Handler] = {}
        self._notification_tasks: set[asyncio.Task] = set()
        self._reader_task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        await self.transport.start()
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def request(self, method: str, params: Any = None, *, timeout: float | None = None) -> Any:
        if self._closed:
            raise AcpTransportError("JSON-RPC peer is closed")
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.transport.send_json(message)
            return await asyncio.wait_for(future, timeout=timeout or self.request_timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            raise AcpTimeoutError(f"JSON-RPC request timed out: {method}") from exc
        except Exception:
            self._pending.pop(request_id, None)
            raise

    async def notify(self, method: str, params: Any = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self.transport.send_json(message)

    def on_request(self, method: str, handler: Handler) -> None:
        self._request_handlers[method] = handler

    def on_notification(self, method: str, handler: Handler) -> None:
        self._notification_handlers[method] = handler

    async def close(self) -> None:
        self._closed = True
        await self.cancel_pending(AcpTransportError("JSON-RPC peer closed"))
        task = self._reader_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        await self._cancel_notification_tasks()
        await self.transport.close()

    async def cancel_pending(self, exc: BaseException | None = None) -> None:
        exc = exc or AcpTransportError("pending JSON-RPC requests cancelled")
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)

    def pending_count(self) -> int:
        return len(self._pending)

    async def _reader_loop(self) -> None:
        try:
            while not self._closed:
                try:
                    message = await self.transport.read_json()
                except AcpTimeoutError:
                    continue
                await self._route(message)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await self.cancel_pending(exc)

    async def _route(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        has_id = "id" in message
        has_method = isinstance(message.get("method"), str)
        has_result = "result" in message
        has_error = "error" in message
        is_pending_response = has_id and request_id in self._pending
        if is_pending_response:
            if message.get("jsonrpc") != "2.0":
                self._reject_invalid_response(request_id, "invalid JSON-RPC version")
            elif has_method:
                self._reject_invalid_response(request_id, "response must not include method")
            elif has_result and has_error:
                self._reject_invalid_response(request_id, "conflicting result and error fields")
            elif has_result or has_error:
                self._handle_response(message)
            else:
                self._reject_invalid_response(request_id, "missing result or error field")
            return
        if message.get("jsonrpc") != "2.0":
            if has_id and has_method:
                await self._send_invalid_request(request_id)
                return
            self.debug_log.system("invalid JSON-RPC version", kind="error")
            return
        if has_method and has_id:
            if has_result or has_error:
                await self._send_invalid_request(request_id)
                return
            await self._handle_inbound_request(message)
        elif has_method:
            if has_result or has_error:
                self.debug_log.system("invalid JSON-RPC notification shape", kind="error")
                return
            self._handle_notification(message)
        elif has_id and (has_result or has_error):
            if has_result and has_error:
                self._reject_invalid_response(request_id, "conflicting result and error fields")
                return
            self._handle_response(message)
        else:
            if has_id:
                self.debug_log.system(f"invalid JSON-RPC response id {request_id}: missing result or error field", kind="error")
            else:
                self.debug_log.system("invalid JSON-RPC message shape", kind="error")

    def _reject_invalid_response(self, request_id: Any, message: str) -> None:
        future = self._pending.pop(request_id, None)
        self.debug_log.system(f"invalid JSON-RPC response id {request_id}: {message}", kind="error")
        if future is not None and not future.done():
            future.set_exception(AcpProtocolError(message))

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        future = self._pending.pop(request_id, None)
        if future is None:
            self.debug_log.system(f"unknown JSON-RPC response id: {request_id}", kind="error")
            return
        if future.done():
            return
        if "error" in message:
            error = message.get("error") or {}
            if isinstance(error, dict):
                future.set_exception(AcpJsonRpcError(error.get("code"), str(error.get("message", "JSON-RPC error")), error.get("data")))
            else:
                future.set_exception(AcpJsonRpcError(None, "JSON-RPC error"))
        else:
            future.set_result(message.get("result"))

    def _handle_notification(self, message: dict[str, Any]) -> None:
        handler = self._notification_handlers.get(message["method"])
        if handler is None:
            return
        task = asyncio.create_task(self._call_notification(handler, message.get("params")))
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_tasks.discard)

    async def _call_notification(self, handler: Handler, params: Any) -> None:
        try:
            result = handler(params)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.debug_log.system(f"notification handler failed: {exc}", kind="error")

    async def _handle_inbound_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message["method"]
        handler = self._request_handlers.get(method)
        if handler is None:
            await self.transport.send_json({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})
            return
        try:
            result = handler(message.get("params"))
            if inspect.isawaitable(result):
                result = await result
            await self.transport.send_json({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            await self.transport.send_json({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc) or "Internal error"}})

    async def _send_invalid_request(self, request_id: Any) -> None:
        await self.transport.send_json({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}})

    async def _cancel_notification_tasks(self) -> None:
        tasks = list(self._notification_tasks)
        self._notification_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
