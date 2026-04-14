#!/usr/bin/env python3
"""
Docker MCP Gateway Proxy
Converts stdio to HTTP streaming for Docker MCP Gateway
"""
import sys
import json
import requests
import threading
import queue

import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://host.docker.internal:8815")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "tyw23wje5kvv0my0yedlcqgl6u3ae27zguuyqzcpx7va9b16h1")
SESSION_ID = None

input_queue = queue.Queue()
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json"
})

def reader_thread():
    """Read from stdin and queue messages"""
    buffer = ""
    while True:
        try:
            chunk = sys.stdin.read(1)
            if not chunk:
                break
            buffer += chunk
            if buffer.endswith('\n'):
                try:
                    msg = json.loads(buffer.strip())
                    input_queue.put(msg)
                    buffer = ""
                except json.JSONDecodeError:
                    pass  # Wait for more data
        except Exception as e:
            print(f"Reader error: {e}", file=sys.stderr)
            break

def writer_thread():
    """Send messages to gateway and write responses"""
    global SESSION_ID
    
    # Initialize session
    try:
        resp = session.post(f"{GATEWAY_URL}/sse", json={})
        if resp.status_code == 200:
            data = resp.text
            if "sessionid" in data.lower():
                # Extract session ID from SSE event
                for line in data.split('\n'):
                    if 'data:' in line and 'sessionid' in line.lower():
                        SESSION_ID = line.split('sessionid=')[1].strip() if 'sessionid=' in line else None
                        break
    except Exception as e:
        print(f"Init error: {e}", file=sys.stderr)
    
    while True:
        try:
            msg = input_queue.get(timeout=1)
            
            # Add session ID if available
            if SESSION_ID:
                msg['_session'] = SESSION_ID
            
            # Send to gateway
            resp = session.post(f"{GATEWAY_URL}/message", json=msg)
            
            if resp.status_code == 200:
                result = resp.json()
                print(json.dumps(result), flush=True)
            else:
                error_msg = {"error": f"HTTP {resp.status_code}: {resp.text}"}
                print(json.dumps(error_msg), flush=True)
                
        except queue.Empty:
            continue
        except Exception as e:
            error_msg = {"error": f"Gateway error: {str(e)}"}
            print(json.dumps(error_msg), flush=True)

if __name__ == "__main__":
    # Start reader and writer threads
    reader = threading.Thread(target=reader_thread, daemon=True)
    writer = threading.Thread(target=writer_thread, daemon=True)
    
    reader.start()
    writer.start()
    
    # Wait for threads
    reader.join()
    writer.join()
