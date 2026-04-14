#!/bin/bash

# ==============================================================================
# Auto-configure MCP Servers in Agent-Zero container
# ==============================================================================
# Usage: ./auto_configure_docker_mcp.sh <container_name> [chrome_port] [mcp_proxy_port] [mcp_auth_token]
# ==============================================================================

CONTAINER_NAME="${1:-a0-agent}"
CHROME_DEBUG_PORT="${2:-9222}"
MCP_PROXY_PORT="${3:-8813}"
MCP_AUTH_TOKEN="${4:-agent-zero-mcp-2024}"

echo "🔧 Auto-configuring MCP servers in container: ${CONTAINER_NAME}"
echo "   Docker MCP SSE:    http://host.docker.internal:${MCP_PROXY_PORT}/sse (disabled by default)"
echo "   Chrome DevTools:   port ${CHROME_DEBUG_PORT}"

# Copy Chrome MCP server script to container
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/chrome_mcp_server.py" ]; then
    echo "📦 Copying chrome_mcp_server.py to container..."
    docker cp "${SCRIPT_DIR}/chrome_mcp_server.py" "${CONTAINER_NAME}:/a0/chrome_mcp_server.py" && \
        echo "  ✅ chrome_mcp_server.py copied" || \
        echo "  ⚠️  Failed to copy chrome_mcp_server.py"
fi

# Install required Python packages in container
echo "📦 Installing Python dependencies..."
docker exec "${CONTAINER_NAME}" bash -c "
    pip3 install --break-system-packages -q websockets aiohttp mcp 2>/dev/null
" && echo "  ✅ Dependencies installed" || echo "  ⚠️  Some deps may have failed"

# Write MCP configuration to /a0/usr/settings.json
echo "⚙️  Writing MCP configuration..."
docker exec "${CONTAINER_NAME}" python3 - <<PYEOF
import json, os

# /a0/usr is the persistent user data directory
os.makedirs('/a0/usr', exist_ok=True)
settings_path = '/a0/usr/settings.json'

# Load existing settings
try:
    with open(settings_path, 'r') as f:
        settings = json.load(f)
except Exception:
    settings = {}

# Configure MCP servers:
# - docker-mcp-toolkit: reaches the host MCP gateway via socat proxy + auth token
#   (disabled by default — enable in Settings if container→host SSE works on your setup)
# - chrome-devtools: runs inside container, connects to Chrome on host
mcp_servers = [
    {
        "name": "docker-mcp-toolkit",
        "description": "Docker MCP Toolkit - control Docker from inside the container",
        "type": "sse",
        "url": "http://host.docker.internal:${MCP_PROXY_PORT}/sse",
        "headers": {"Authorization": "Bearer ${MCP_AUTH_TOKEN}"},
        "disabled": True
    },
    {
        "name": "chrome-devtools",
        "description": "Chrome DevTools - controls Chrome on your Mac",
        "type": "stdio",
        "command": "python3",
        "args": ["/a0/chrome_mcp_server.py"],
        "env": {
            "CHROME_DEBUG_PORT": "${CHROME_DEBUG_PORT}",
            "CHROME_HOST": "host.docker.internal"
        },
        "disabled": False
    }
]

settings["mcp_servers"] = json.dumps(mcp_servers)

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=4)

print("  ✅ settings.json updated with Docker MCP + Chrome DevTools")
PYEOF

echo "✅ Auto-configuration complete!"
echo "   Docker MCP:    http://host.docker.internal:${MCP_PROXY_PORT}/sse (disabled — enable in Settings)"
echo "   Chrome MCP:    stdio /a0/chrome_mcp_server.py (port ${CHROME_DEBUG_PORT})"
