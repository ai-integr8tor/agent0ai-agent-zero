from __future__ import annotations

import asyncio
import json
import sys
import textwrap

import pytest

from helpers.acp.debug_log import DebugLog
from helpers.acp.errors import AcpJsonRpcError, AcpProtocolError, AcpTimeoutError, AcpTransportError
from helpers.acp.jsonrpc import JsonRpcPeer
from helpers.acp.transport import StdioTransport


async def _peer_for_script(tmp_path, source: str, **peer_kwargs):
    script = tmp_path / "server.py"
    script.write_text(textwrap.dedent(source))
    debug_log = peer_kwargs.pop("debug_log", None)
    request_timeout = peer_kwargs.pop("request_timeout", 2)
    transport_operation_timeout = peer_kwargs.pop("transport_operation_timeout", 2)
    transport = StdioTransport([sys.executable, str(script)], operation_timeout=transport_operation_timeout, debug_log=debug_log)
    peer = JsonRpcPeer(transport, request_timeout=request_timeout, **peer_kwargs)
    await peer.start()
    return peer


@pytest.mark.asyncio
async def test_jsonrpc_request_response_matching_with_out_of_order_replies(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys, threading, time
        def respond(msg):
            if msg["params"]["value"] == "slow": time.sleep(0.2)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":msg["params"]}), flush=True)
        for line in sys.stdin:
            threading.Thread(target=respond, args=(json.loads(line),), daemon=False).start()
    """)
    try:
        slow = asyncio.create_task(peer.request("echo", {"value": "slow"}))
        fast = asyncio.create_task(peer.request("echo", {"value": "fast"}))
        assert await fast == {"value": "fast"}
        assert await slow == {"value": "slow"}
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_notifications_dispatch_without_blocking_response(tmp_path):
    seen: list[dict] = []
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","method":"notice","params":{"from":"server"}}), flush=True)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":"ok"}), flush=True)
    """)
    peer.on_notification("notice", lambda params: seen.append(params))
    try:
        assert await peer.request("work") == "ok"
        await asyncio.sleep(0.1)
        assert seen == [{"from": "server"}]
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_remote_error_and_timeout_clean_pending(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys, time
        for line in sys.stdin:
            msg=json.loads(line)
            if msg["method"] == "error":
                print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"error":{"code":-32601,"message":"Method not found"}}), flush=True)
            else:
                time.sleep(5)
    """, request_timeout=0.2)
    try:
        with pytest.raises(AcpJsonRpcError):
            await peer.request("error")
        with pytest.raises(AcpTimeoutError):
            await peer.request("slow")
        assert peer.pending_count() == 0
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_inbound_request_handler_sends_result(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        print(json.dumps({"jsonrpc":"2.0","id":99,"method":"local/echo","params":{"n":4}}), flush=True)
        for line in sys.stdin:
            msg=json.loads(line)
            if msg.get("id") == 99:
                print(json.dumps({"jsonrpc":"2.0","id":1,"result":msg["result"]}), flush=True)
    """)
    peer.on_request("local/echo", lambda params: {"seen": params["n"]})
    try:
        assert await peer.request("trigger") == {"seen": 4}
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_process_exit_rejects_pending_requests(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys, os
        for line in sys.stdin:
            os._exit(2)
    """)
    try:
        with pytest.raises(AcpTransportError):
            await peer.request("die")
        assert peer.pending_count() == 0
    finally:
        await peer.close()


def test_jsonrpc_debug_log_classifies_messages():
    log = DebugLog()
    log.inbound({"jsonrpc":"2.0","method":"notice","params":{}})
    log.outbound({"jsonrpc":"2.0","id":1,"result":"ok"})
    assert [record["kind"] for record in log.snapshot()] == ["notification", "response"]

@pytest.mark.asyncio
async def test_jsonrpc_idle_transport_timeout_does_not_kill_peer(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":"after-idle"}), flush=True)
    """, request_timeout=1, transport_operation_timeout=0.2)
    try:
        await asyncio.sleep(0.35)
        assert await peer.request("after/idle") == "after-idle"
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_unknown_request_and_invalid_request_get_structured_errors(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        trigger=json.loads(sys.stdin.readline())
        print(json.dumps({"jsonrpc":"2.0","id":10,"method":"missing"}), flush=True)
        print(json.dumps({"jsonrpc":"2.0","id":11,"method":"bad","result":"conflict"}), flush=True)
        responses=[]
        while len(responses) < 2:
            line=sys.stdin.readline()
            if not line: break
            responses.append(json.loads(line))
        print(json.dumps({"jsonrpc":"2.0","id":trigger["id"],"result":responses}), flush=True)
    """)
    try:
        responses = await peer.request("collect")
        errors = {response["id"]: response["error"]["code"] for response in responses}
        assert errors == {10: -32601, 11: -32600}
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_close_cancels_notification_tasks(tmp_path):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","method":"slow/notice","params":{}}), flush=True)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":"ok"}), flush=True)
    """)

    async def slow_handler(params):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    peer.on_notification("slow/notice", slow_handler)
    assert await peer.request("start") == "ok"
    await asyncio.wait_for(started.wait(), timeout=1)
    await peer.close()
    await asyncio.wait_for(cancelled.wait(), timeout=1)


def test_jsonrpc_unknown_response_is_logged_not_crashing():
    log = DebugLog()
    log.system("unknown JSON-RPC response id: 42", kind="error")
    assert log.snapshot()[0]["kind"] == "error"


@pytest.mark.asyncio
async def test_jsonrpc_invalid_response_rejects_matching_pending_request(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":"ok","error":{"code":-32603,"message":"bad"}}), flush=True)
    """)
    try:
        with pytest.raises(AcpProtocolError):
            await peer.request("bad/response")
        assert peer.pending_count() == 0
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_invalid_version_response_rejects_pending_request(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"1.0","id":msg["id"],"result":"wrong-version"}), flush=True)
    """)
    try:
        with pytest.raises(AcpProtocolError):
            await peer.request("bad/version")
        assert peer.pending_count() == 0
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_id_only_response_rejects_pending_request(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"]}), flush=True)
    """)
    try:
        with pytest.raises(AcpProtocolError):
            await peer.request("bad/id-only")
        assert peer.pending_count() == 0
    finally:
        await peer.close()


@pytest.mark.asyncio
async def test_jsonrpc_pending_id_with_method_and_result_rejects_pending_request(tmp_path):
    peer = await _peer_for_script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg=json.loads(line)
            print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"method":"not/a/request","result":"bad"}), flush=True)
    """)
    try:
        with pytest.raises(AcpProtocolError):
            await peer.request("bad/method-result")
        assert peer.pending_count() == 0
    finally:
        await peer.close()
