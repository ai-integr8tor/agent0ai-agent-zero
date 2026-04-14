# Docker MCP Toolkit Setup Guide for Agent-Zero

## 🐳 **What is Docker MCP Toolkit?**

The Docker MCP (Model Context Protocol) toolkit allows Agent-Zero to interact with Docker containers and manage Docker operations directly from within the agent.

## 🚀 **How It Works**

The `run_a0.sh` startup script automatically:
1. **Starts the Docker MCP Gateway** on localhost:8811
2. **Starts a socat proxy** on 0.0.0.0:8813 → 127.0.0.1:8811
3. **Launches the container** with `--add-host=host.docker.internal:host-gateway`
4. **Configures MCP servers** in settings

```
Mac Host                          Docker Container
┌──────────────────┐              ┌──────────────────┐
│ Docker MCP       │   socat      │  Agent-Zero      │
│ Gateway :8811    │◄────────────►│  MCP Client      │
│ (localhost)      │  :8813       │  (sse_client)    │
│                  │              │                  │
│ Chrome :9222     │              │  Chrome MCP      │
│                  │              │  Server (stdio)  │
└──────────────────┘              └──────────────────┘
```

## ⚠️ **Default State**

The Docker MCP Toolkit is **disabled by default** (`"disabled": true`) in the MCP server config. This is because the SSE connection from inside the container to `host.docker.internal` can fail on some Docker setups (especially Docker Desktop for Mac).

**To enable it:**
1. Open Agent-Zero Settings → MCP Servers
2. Find `docker-mcp-toolkit` and toggle it ON
3. Save/Apply the settings
4. If the connection succeeds, you'll see Docker tools available

**If it fails to connect**, check:
- The gateway is running: `lsof -i :8811` should show a listening process
- The socat proxy is running: `lsof -i :8813` should show a listening process
- `host.docker.internal` resolves inside the container: `docker exec <container> getent host host.docker.internal`

## 📋 **MCP Configuration**

### Via `run_a0.sh` (automatic)
The startup script writes the MCP config automatically. No manual steps needed.

### Manual config in Settings UI
```json
[
  {
    "name": "docker-mcp-toolkit",
    "description": "Docker MCP Toolkit - control Docker from inside the container",
    "type": "sse",
    "url": "http://host.docker.internal:8813/sse",
    "headers": {"Authorization": "Bearer agent-zero-mcp-2024"},
    "disabled": false
  },
  {
    "name": "chrome-devtools",
    "description": "Chrome DevTools - controls Chrome on your Mac",
    "type": "stdio",
    "command": "python3",
    "args": ["/a0/chrome_mcp_server.py"],
    "env": {
      "CHROME_DEBUG_PORT": "9222",
      "CHROME_HOST": "host.docker.internal"
    },
    "disabled": false
  }
]
```

## 🐳 **Available Docker MCP Tools**

Once configured and connected, Agent-Zero can use Docker tools like:

- **Container Management**: List, start, stop, restart containers
- **Image Operations**: Pull, build, inspect images
- **Network Management**: Create, list networks
- **Volume Operations**: Create, list, manage volumes
- **Docker Compose**: Run multi-container applications
- **Log Access**: View container logs
- **Exec Commands**: Run commands inside containers

## 🛠️ **Troubleshooting**

### Docker MCP Not Connecting
```bash
# Check gateway is running
lsof -i :8811
lsof -i :8813

# Check socat proxy
ps aux | grep socat

# Test from inside container
docker exec a0-agent curl -s http://host.docker.internal:8813/sse

# Check gateway logs
cat /tmp/docker_mcp_gateway.log
```

### Chrome DevTools Not Connecting
```bash
# Test connection from container
docker exec a0-agent curl -H "Host: localhost" http://host.docker.internal:9222/json/version
```

### Container can't reach host.docker.internal
```bash
# Inside container, test resolution
docker exec a0-agent getent hosts host.docker.internal

# Should return an IP like 192.168.65.254 or 172.17.0.1
```

## 🔄 **Updates and Maintenance**

### Updating Docker MCP:
- The gateway is managed by the `docker mcp` CLI
- Update Docker Desktop to get latest MCP support

### Configuration Changes:
- Update MCP server config in Agent-Zero settings
- Restart Agent-Zero container for changes to take effect
- Test connection after any configuration changes

---

## 🎯 **Quick Reference**

### Start Agent-Zero with Docker MCP:
```bash
./run_a0.sh
```

### Ports:
- **Agent-Zero**: 55080
- **Docker MCP Gateway**: 8811 (localhost)
- **Socat Proxy**: 8813 (0.0.0.0 → 127.0.0.1:8811)
- **Chrome Debug**: 9222

### Key Files:
- **Settings**: `/a0/usr/settings.json` (in container)
- **Gateway Log**: `/tmp/docker_mcp_gateway.log` (on host)
- **Socat Log**: `/tmp/socat_mcp_proxy.log` (on host)
