# Docker MCP Setup - Issue Summary

## Original Problem
User wanted Docker MCP tools working in Agent-Zero with:
1. **Docker MCP Toolkit** - Docker Desktop integration via socat
2. **Chrome DevTools** - Browser automation for container

Error: `McpError: Timed out while waiting for response to ClientRequest`

---

## What We Tried

### Attempt 1: Socat Tunnel (STDIO)
```json
{
  "command": "docker",
  "args": ["run", "-i", "--rm", "alpine/socat", "STDIO", "TCP:host.docker.internal:8811"]
}
```
**Result:** ❌ FAILED
- Port 8811 blocked by Docker Desktop internal service
- No actual MCP server running on that port

### Attempt 2: Docker MCP Gateway (SSE)
- Started `docker mcp gateway run --transport sse --port 8811`
- Gateway runs successfully with 200+ MCP servers
**Result:** ❌ FAILED
- Container cannot reach `host.docker.internal:8811` from inside Docker on macOS
- Docker Desktop networking blocks container→host SSE connections

### Attempt 3: Chrome DevTools MCP Server (STDIO)
- Created custom Python MCP server (`chrome_mcp_server.py`)
- Runs INSIDE container, connects to Chrome on host via CDP
**Result:** ✅ WORKING

---

## What WORKS ✅

### Chrome DevTools MCP
- **7 tools available:** navigate, screenshot, get_html, click, type_text, evaluate_javascript, get_console_logs
- Chrome runs on host (port 9222) with `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0`
- Container connects via `host.docker.internal` (resolves to 192.168.65.254)
- MCP server uses `Host: localhost` header to bypass Chrome host validation

**Working Config:**
```json
{
  "mcpServers": {
    "chrome-devtools": {
      "name": "chrome-devtools",
      "description": "Chrome DevTools - Controls Chrome on your Mac",
      "type": "stdio",
      "command": "python3",
      "args": ["/a0/chrome_mcp_server.py"],
      "env": {
        "CHROME_DEBUG_PORT": "9222",
        "CHROME_HOST": "host.docker.internal"
      },
      "disabled": false
    }
  }
}
```

**Files:**
- `/Users/davidandrews/PycharmProjects/agent-zero/chrome_mcp_server.py` - MCP server
- `/Users/davidandrews/PycharmProjects/agent-zero/docker_mcp_config.json` - Config file
- `/Users/davidandrews/PycharmProjects/agent-zero/run_agent_zero_normal.sh` - Starts Chrome + container
- `/Users/davidandrews/PycharmProjects/agent-zero/auto_configure_docker_mcp.sh` - Copies server to container

---

## What DOESN'T WORK ❌

### Docker MCP Toolkit (Docker Desktop Integration)
**Problem:** Container cannot reach Docker MCP Gateway on host

**Root Cause:** Docker Desktop for Mac networking limitation
- `host.docker.internal` resolves to 192.168.65.254 (Docker VM)
- Container runs on 172.17.0.0/16 network
- Gateway binds to host loopback, not accessible from container network
- SSE connections timeout from container

**Tested:**
```bash
# From container - all fail
curl http://host.docker.internal:8811/sse  # Times out
curl http://172.17.0.1:8811/sse            # Connection refused
curl http://192.168.65.1:8811/sse          # Times out
```

**Possible Solutions (Not Implemented):**
1. Run Docker MCP Gateway in separate container with `--network host`
2. Use Docker Desktop's experimental networking features
3. Find alternative Docker MCP server that works from containers

---

## Current State

### Working
- ✅ Chrome DevTools MCP (7 tools)
- ✅ Chrome runs on host port 9222
- ✅ Container connects successfully
- ✅ Auto-configuration script copies server + installs dependencies

### Not Working
- ❌ Docker MCP Toolkit (networking limitation)
- ⚠️ Old `docker_mcp_toolkit` config cached in Agent-Zero UI

### Required Manual Step
Agent-Zero UI caches old MCP config. User must:
1. Go to Settings → MCP Servers
2. Paste Chrome-only config (above)
3. Save/Apply

---

## For Next Developer

### If you want to fix Docker MCP Toolkit:
1. Need to solve container→host SSE connectivity on Docker Desktop Mac
2. Options:
   - Run gateway in container with shared network
   - Use Docker Desktop networking APIs
   - Find alternative Docker MCP server that works from containers

### Chrome DevTools is DONE:
- Works perfectly
- Just needs UI config update to clear cached errors

### Key Files to Review:
```
chrome_mcp_server.py          # Chrome MCP implementation
run_agent_zero_normal.sh      # Startup script (starts Chrome)
auto_configure_docker_mcp.sh  # Copies server, installs deps
docker_mcp_config.json        # Current config (Chrome only)
```

### Test Commands:
```bash
# Start everything
./run_agent_zero_normal.sh

# Test Chrome from container
docker exec agent-zero-normal curl -H "Host: localhost" http://host.docker.internal:9222/json/version

# Test MCP server
docker exec agent-zero-normal timeout 3 python3 /a0/chrome_mcp_server.py

# Check logs
docker logs agent-zero-normal 2>&1 | grep -i chrome
```
