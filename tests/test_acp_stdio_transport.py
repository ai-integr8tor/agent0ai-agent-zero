from __future__ import annotations

import asyncio
import os
import sys
import textwrap

import pytest

from helpers.acp.debug_log import DebugLog
from helpers.acp.errors import AcpProcessExitedError, AcpProtocolError, AcpTransportError
from helpers.acp.transport import StdioTransport


@pytest.mark.asyncio
async def test_transport_launches_fake_process_and_round_trips_json(tmp_path):
    script = tmp_path / "echo_server.py"
    script.write_text(textwrap.dedent("""
        import json, sys
        for line in sys.stdin:
            obj = json.loads(line)
            print(json.dumps({"ok": obj}), flush=True)
    """))
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=2)
    await transport.start()
    try:
        await transport.send_json({"hello": "world"})
        assert await transport.read_json() == {"ok": {"hello": "world"}}
        assert transport.is_running() is True
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_captures_stderr_as_diagnostics_only(tmp_path):
    script = tmp_path / "stderr_server.py"
    script.write_text(textwrap.dedent("""
        import json, sys
        print("warning secret", file=sys.stderr, flush=True)
        for line in sys.stdin:
            print(json.dumps({"jsonrpc":"2.0","id":1,"result":"ok"}), flush=True)
    """))
    log = DebugLog(masker=lambda text: text.replace("secret", "***"))
    transport = StdioTransport([sys.executable, str(script)], debug_log=log, operation_timeout=2)
    await transport.start()
    try:
        await asyncio.sleep(0.1)
        await transport.send_json({"jsonrpc":"2.0","id":1,"method":"x"})
        assert await transport.read_json() == {"jsonrpc": "2.0", "id": 1, "result": "ok"}
        assert any(record["direction"] == "stderr" and "***" in record["preview"] for record in transport.diagnostics())
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_malformed_stdout_marks_unhealthy(tmp_path):
    script = tmp_path / "bad_server.py"
    script.write_text('print("not json", flush=True)\nimport time; time.sleep(5)\n')
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=2)
    await transport.start()
    try:
        with pytest.raises(AcpProtocolError):
            await transport.read_json()
        with pytest.raises(AcpTransportError):
            await transport.send_json({"still": "there"})
    finally:
        await transport.kill()


@pytest.mark.asyncio
async def test_transport_rejects_string_command_and_missing_cwd(tmp_path):
    with pytest.raises(AcpTransportError):
        StdioTransport("python -V")  # type: ignore[arg-type]
    with pytest.raises(AcpTransportError):
        StdioTransport([sys.executable, "-V"], cwd=tmp_path / "missing")


@pytest.mark.asyncio
async def test_transport_process_exit_is_reported(tmp_path):
    script = tmp_path / "exit_server.py"
    script.write_text('import sys; sys.exit(3)\n')
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=0.5)
    await transport.start()
    try:
        with pytest.raises(AcpProcessExitedError):
            await transport.read_json()
    finally:
        await transport.kill()

@pytest.mark.asyncio
async def test_transport_oversized_stdout_marks_unhealthy(tmp_path):
    script = tmp_path / "large_server.py"
    script.write_text('print("{\\\"payload\\\":\\\"" + "x" * 64 + "\\\"}", flush=True)\nimport time; time.sleep(5)\n')
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=2, max_line_bytes=20)
    await transport.start()
    try:
        with pytest.raises(AcpProtocolError):
            await transport.read_json()
        with pytest.raises(AcpTransportError):
            await transport.read_json()
    finally:
        await transport.kill()


@pytest.mark.asyncio
async def test_transport_close_and_kill_are_idempotent(tmp_path):
    script = tmp_path / "sleep_server.py"
    script.write_text('import time; time.sleep(30)\n')
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=1, close_timeout=0.1)
    await transport.start()
    await transport.close()
    await transport.close()
    await transport.kill()
    await transport.kill()
    assert transport.is_running() is False


@pytest.mark.asyncio
async def test_transport_logs_outbound_before_failed_write(tmp_path):
    script = tmp_path / "exit_server.py"
    script.write_text('import sys; sys.exit(0)\n')
    log = DebugLog()
    transport = StdioTransport([sys.executable, str(script)], debug_log=log, operation_timeout=0.2)
    await transport.start()
    await asyncio.sleep(0.1)
    with pytest.raises(AcpTransportError):
        await transport.send_json({"jsonrpc": "2.0", "id": 1, "method": "will/fail"})
    assert any(record["direction"] == "outbound" and record["method"] == "will/fail" for record in log.snapshot())
    with pytest.raises(AcpTransportError):
        await transport.send_json({"jsonrpc": "2.0", "id": 2, "method": "fast/fail"})


@pytest.mark.asyncio
async def test_transport_returncode_read_path_marks_unhealthy(tmp_path):
    script = tmp_path / "exit_before_read.py"
    script.write_text('import sys; sys.exit(0)\n')
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=1)
    await transport.start()
    await asyncio.sleep(0.1)
    try:
        with pytest.raises(AcpProcessExitedError):
            await transport.read_json()
        with pytest.raises(AcpTransportError):
            await transport.read_json()
    finally:
        await transport.kill()
