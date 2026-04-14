#!/usr/bin/env python3
"""
Chrome DevTools MCP Server for Docker Container
Connects to Chrome running on host via host.docker.internal
"""
import os
import sys
import asyncio
import json
import websockets
import aiohttp
from mcp.server.fastmcp import FastMCP

# Chrome debug port on host (passed via environment)
CHROME_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
CHROME_HOST = os.getenv("CHROME_HOST", "host.docker.internal")

# Try to resolve Chrome host - fallback to gateway IP
import socket
try:
    CHROME_IP = socket.gethostbyname(CHROME_HOST)
except:
    CHROME_IP = "172.17.0.1"  # Default Docker gateway

# Create MCP server
mcp = FastMCP("Chrome DevTools MCP")

# Global WebSocket connection
ws_connection = None
ws_url = None

async def get_chrome_ws_url():
    """Get Chrome WebSocket URL from debug port"""
    global ws_url
    if ws_url:
        return ws_url
    
    try:
        # Get available targets from Chrome - use IP with localhost host header
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{CHROME_IP}:{CHROME_DEBUG_PORT}/json/version",
                headers={"Host": "localhost"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ws_url = data.get("webSocketDebuggerUrl")
                    # Replace localhost with actual IP in WS URL if needed
                    if ws_url and "localhost" in ws_url:
                        ws_url = ws_url.replace("localhost", CHROME_IP)
                    return ws_url
    except Exception as e:
        print(f"Error getting Chrome WS URL: {e}", file=sys.stderr)
    
    # Fallback: construct URL manually
    ws_url = f"ws://{CHROME_IP}:{CHROME_DEBUG_PORT}/devtools/browser"
    return ws_url

async def send_cdp_command(method, params=None):
    """Send CDP command to Chrome"""
    global ws_connection
    
    try:
        ws_url = await get_chrome_ws_url()
        
        if ws_connection is None:
            ws_connection = await websockets.connect(ws_url)
        
        message_id = 1
        message = {
            "id": message_id,
            "method": method,
            "params": params or {}
        }
        
        await ws_connection.send(json.dumps(message))
        response = await ws_connection.recv()
        return json.loads(response)
        
    except Exception as e:
        ws_connection = None  # Reset connection on error
        raise Exception(f"CDP command failed: {e}")

@mcp.tool()
async def navigate(url: str) -> str:
    """Navigate to a URL in Chrome"""
    try:
        result = await send_cdp_command("Page.navigate", {"url": url})
        return f"Navigated to {url}"
    except Exception as e:
        return f"Navigation failed: {e}"

@mcp.tool()
async def screenshot() -> str:
    """Take a screenshot of the current page"""
    try:
        result = await send_cdp_command("Page.captureScreenshot", {"format": "png"})
        return "Screenshot captured (base64 data available)"
    except Exception as e:
        return f"Screenshot failed: {e}"

@mcp.tool()
async def get_html() -> str:
    """Get the HTML content of the current page"""
    try:
        # Get root node
        result = await send_cdp_command("DOM.getDocument")
        root_id = result["root"]["nodeId"]
        
        # Get outer HTML
        result = await send_cdp_command("DOM.getOuterHTML", {"nodeId": root_id})
        return result["outerHTML"][:5000]  # Truncate for readability
    except Exception as e:
        return f"Get HTML failed: {e}"

@mcp.tool()
async def click(selector: str) -> str:
    """Click an element matching the CSS selector"""
    try:
        # Query selector
        result = await send_cdp_command("DOM.querySelector", {
            "nodeId": 1,
            "selector": selector
        })
        
        if result["nodeId"] == 0:
            return f"Element not found: {selector}"
        
        # Scroll into view
        await send_cdp_command("DOM.scrollIntoViewIfNeeded", {
            "nodeId": result["nodeId"]
        })
        
        # Click
        await send_cdp_command("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": 0,
            "y": 0,
            "button": "left"
        })
        await send_cdp_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": 0,
            "y": 0,
            "button": "left"
        })
        
        return f"Clicked: {selector}"
    except Exception as e:
        return f"Click failed: {e}"

@mcp.tool()
async def type_text(selector: str, text: str) -> str:
    """Type text into an input field"""
    try:
        # Query selector
        result = await send_cdp_command("DOM.querySelector", {
            "nodeId": 1,
            "selector": selector
        })
        
        if result["nodeId"] == 0:
            return f"Element not found: {selector}"
        
        # Focus
        await send_cdp_command("DOM.focus", {"nodeId": result["nodeId"]})
        
        # Type each character
        for char in text:
            await send_cdp_command("Input.dispatchKeyEvent", {
                "type": "char",
                "text": char
            })
        
        return f"Typed '{text}' into {selector}"
    except Exception as e:
        return f"Type failed: {e}"

@mcp.tool()
async def get_console_logs() -> str:
    """Get console logs from the page"""
    try:
        # Enable runtime domain
        await send_cdp_command("Runtime.enable")
        
        # This would need event handling - simplified for now
        return "Console log retrieval requires event listener setup"
    except Exception as e:
        return f"Get logs failed: {e}"

@mcp.tool()
async def evaluate_javascript(expression: str) -> str:
    """Execute JavaScript in the page context"""
    try:
        result = await send_cdp_command("Runtime.evaluate", {
            "expression": expression
        })
        
        if "result" in result:
            return str(result["result"])
        return "Execution completed"
    except Exception as e:
        return f"JS evaluation failed: {e}"

if __name__ == "__main__":
    print(f"Chrome DevTools MCP Server")
    print(f"Connecting to {CHROME_HOST}:{CHROME_DEBUG_PORT}")
    mcp.run()
