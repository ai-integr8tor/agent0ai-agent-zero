#!/bin/bash

# ==============================================================================
# Agent-Zero Runner (Unified Script)
# ==============================================================================
# Starts Agent-Zero container with Docker MCP gateway + socat proxy
# Files persist locally in ./a0/ folder
# Usage: ./run_a0.sh [-H|--hacking] [docker args...]
# ==============================================================================

# --- Script Configuration ---
set -e
set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- User-Friendly Colors ---
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'
NC='\033[0m'

# --- Docker MCP Gateway Config ---
MCP_GATEWAY_PORT=8811       # gateway binds on localhost only
MCP_PROXY_PORT=8813         # socat forwards 0.0.0.0:8813 -> 127.0.0.1:8811
MCP_AUTH_TOKEN="agent-zero-mcp-2024"
MCP_SERVERS="docker"        # only load the docker server (fast startup)

# --- Parse Arguments ---
HACKING_MODE=false
DOCKER_EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -H|--hacking)
            HACKING_MODE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [-H|--hacking] [docker args...]"
            echo ""
            echo "Options:"
            echo "  -H, --hacking    Use the hacking edition image"
            echo "  -h, --help       Show this help message"
            echo ""
            echo "Files persist locally in: ./a0/"
            echo ""
            echo "Examples:"
            echo "  $0               # Run standard version"
            echo "  $0 -H            # Run hacking version"
            exit 0
            ;;
        *)
            DOCKER_EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# --- Set Image Based on Mode ---
if [ "$HACKING_MODE" = true ]; then
    IMAGE="agent0ai/agent-zero:hacking"
    EDITION="Hacking Edition"
    EDITION_COLOR="${COLOR_RED}"
    CONTAINER_NAME="a0h-agent"
else
    IMAGE="agent0ai/agent-zero:latest"
    EDITION="Standard Edition"
    EDITION_COLOR="${COLOR_BLUE}"
    CONTAINER_NAME="a0-agent"
fi

# --- Pre-flight Checks ---
if ! command -v docker &> /dev/null; then
    echo -e "${COLOR_RED}Error: 'docker' command not found. Please start Docker Desktop.${NC}"
    exit 1
fi

if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo -e "${COLOR_RED}Error: '.env' file not found.${NC}"
    exit 1
fi

if [ ! -S /var/run/docker.sock ]; then
    echo -e "${COLOR_RED}Error: Docker socket not found. Is Docker Desktop running?${NC}"
    exit 1
fi

# --- Load Environment from .env file ---
echo "Loading environment variables from .env file..."
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^\s*# ]] || [[ -z "$line" ]]; then continue; fi
    export "$line" 2>/dev/null || true
done < "${SCRIPT_DIR}/.env"

if [ -z "${WEB_UI_PORT:-}" ]; then
    echo -e "${COLOR_RED}Error: WEB_UI_PORT not set in .env${NC}"
    exit 1
fi

# --- Ensure local a0/ persistence folder exists ---
A0_DIR="${SCRIPT_DIR}/a0"
mkdir -p "${A0_DIR}"
echo -e "${COLOR_BLUE}📁 Local persistence folder: ${A0_DIR}${NC}"

# --- Stop & clean any old Docker MCP gateway + socat processes ---
echo -e "${COLOR_BLUE}🔄 Cleaning up old MCP gateway processes...${NC}"
pkill -f "docker-mcp.*gateway run.*${MCP_GATEWAY_PORT}" 2>/dev/null || true
pkill -f "docker mcp gateway run.*${MCP_GATEWAY_PORT}" 2>/dev/null || true
pkill -f "socat.*${MCP_PROXY_PORT}" 2>/dev/null || true
sleep 2

# --- Start Docker MCP Gateway (binds to localhost only) ---
echo -e "${COLOR_BLUE}🐳 Starting Docker MCP Gateway on port ${MCP_GATEWAY_PORT}...${NC}"
export MCP_GATEWAY_AUTH_TOKEN="${MCP_AUTH_TOKEN}"
nohup bash -c "export MCP_GATEWAY_AUTH_TOKEN='${MCP_AUTH_TOKEN}'; \
    docker mcp gateway run \
        --transport sse \
        --port ${MCP_GATEWAY_PORT} \
        --servers ${MCP_SERVERS} \
        --long-lived \
        --static \
    > /tmp/docker_mcp_gateway.log 2>&1" &
GATEWAY_PID=$!
echo -e "${COLOR_GREEN}  Gateway PID: ${GATEWAY_PID}${NC}"

# Wait for gateway to start
echo -e "${COLOR_BLUE}  Waiting for gateway to initialize...${NC}"
for i in {1..30}; do
    if lsof -i ":${MCP_GATEWAY_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
        sleep 3
        echo -e "${COLOR_GREEN}  ✅ Gateway is up on port ${MCP_GATEWAY_PORT}${NC}"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo -e "${COLOR_RED}  ❌ Gateway failed to start. Check /tmp/docker_mcp_gateway.log${NC}"
    fi
done

# --- Start socat proxy: 0.0.0.0:MCP_PROXY_PORT -> 127.0.0.1:MCP_GATEWAY_PORT ---
echo -e "${COLOR_BLUE}🔀 Starting socat proxy (0.0.0.0:${MCP_PROXY_PORT} -> 127.0.0.1:${MCP_GATEWAY_PORT})...${NC}"
if ! command -v socat &>/dev/null; then
    echo -e "${COLOR_RED}  ❌ socat not found. Install with: brew install socat${NC}"
    echo -e "${COLOR_YELLOW}  ⚠️  Docker MCP will not be reachable from container without socat.${NC}"
else
    nohup socat TCP-LISTEN:${MCP_PROXY_PORT},bind=0.0.0.0,reuseaddr,fork \
        TCP:127.0.0.1:${MCP_GATEWAY_PORT} \
        > /tmp/socat_mcp_proxy.log 2>&1 &
    SOCAT_PID=$!
    sleep 1
    if lsof -i ":${MCP_PROXY_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
        echo -e "${COLOR_GREEN}  ✅ Socat proxy up (PID: ${SOCAT_PID})${NC}"
    else
        echo -e "${COLOR_RED}  ❌ Socat proxy failed to start${NC}"
    fi
fi

# --- Copy chrome_mcp_server.py into a0/ so container finds it at /a0/ ---
if [ -f "${SCRIPT_DIR}/chrome_mcp_server.py" ]; then
    cp "${SCRIPT_DIR}/chrome_mcp_server.py" "${A0_DIR}/chrome_mcp_server.py"
    echo -e "${COLOR_GREEN}  ✅ Copied chrome_mcp_server.py to a0/${NC}"
fi

# --- Write MCP settings into a0/usr/settings.json ---
echo -e "${COLOR_BLUE}⚙️  Writing MCP configuration to a0/usr/settings.json...${NC}"
mkdir -p "${A0_DIR}/usr"
python3 - <<PYEOF
import json, os

settings_path = "${A0_DIR}/usr/settings.json"

# Load existing settings if present
try:
    with open(settings_path, 'r') as f:
        settings = json.load(f)
except Exception:
    settings = {}

# MCP server list:
#  - docker-mcp-toolkit: SSE via socat proxy (reachable from container via host.docker.internal)
#  - chrome-devtools:    stdio python server inside container
#
# Note: docker-mcp-toolkit is disabled by default because the gateway
# may not be reachable from inside the container on all Docker setups.
# Users can enable it manually in Settings > MCP Servers if their
# environment supports container-to-host SSE connections.
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
            "CHROME_DEBUG_PORT": "9222",
            "CHROME_HOST": "host.docker.internal"
        },
        "disabled": False
    }
]

settings["mcp_servers"] = json.dumps(mcp_servers)

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=4)

print(f"  ✅ Wrote {len(mcp_servers)} MCP servers to {settings_path}")
PYEOF

# --- Stop any old container ---
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${COLOR_YELLOW}🗑️  Removing old container '${CONTAINER_NAME}'...${NC}"
    docker rm -f "${CONTAINER_NAME}" > /dev/null 2>&1 || true
fi

echo -e "\n${COLOR_GREEN}=== Starting Agent-Zero ===${NC}"
echo -e "${EDITION_COLOR}Edition: ${EDITION}${NC}"
echo -e "Image:          ${COLOR_YELLOW}${IMAGE}${NC}"
echo -e "Container:      ${COLOR_YELLOW}${CONTAINER_NAME}${NC}"
echo -e "Access URL:     ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
echo -e "Local data:     ${COLOR_YELLOW}${A0_DIR}${NC}"
echo -e "MCP Gateway:    ${COLOR_YELLOW}localhost:${MCP_GATEWAY_PORT} -> container port ${MCP_PROXY_PORT}${NC}"
echo -e "${COLOR_GREEN}Starting container...${NC}\n"

# --- Run Container ---
# Volume: ./a0 -> /a0  (full persistence: settings, memory, workdir, usr, etc.)
docker run \
  -d \
  --name "${CONTAINER_NAME}" \
  -p "${WEB_UI_PORT}:80" \
  --env-file "${SCRIPT_DIR}/.env" \
  --add-host=host.docker.internal:host-gateway \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${A0_DIR}:/a0" \
  "${IMAGE}" \
  ${DOCKER_EXTRA_ARGS[@]+"${DOCKER_EXTRA_ARGS[@]}"}

echo -e "${COLOR_BLUE}⏳ Waiting for Agent-Zero to start (15s)...${NC}"
sleep 15

# --- Install chrome MCP dependencies inside container ---
if docker exec "${CONTAINER_NAME}" test -f /a0/chrome_mcp_server.py 2>/dev/null; then
    echo -e "${COLOR_BLUE}📦 Installing Chrome MCP Python deps in container...${NC}"
    docker exec "${CONTAINER_NAME}" bash -c \
        "pip3 install --break-system-packages -q websockets aiohttp mcp 2>/dev/null && echo '  ✅ Chrome MCP deps installed'" || true
fi

# --- Verify container running ---
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "\n${COLOR_GREEN}✅ Agent-Zero is running!${NC}"
    echo -e "🌐 Web UI:          ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
    echo -e "📁 Local data:      ${COLOR_YELLOW}${A0_DIR}${NC}"
    echo -e "🐳 Docker MCP:      ${COLOR_YELLOW}SSE → host.docker.internal:${MCP_PROXY_PORT}/sse${NC}"
    echo -e "🌐 Chrome DevTools: ${COLOR_YELLOW}stdio → /a0/chrome_mcp_server.py${NC}"
    echo -e "\n${COLOR_BLUE}📋 Useful commands:${NC}"
    echo -e "   View logs:   ${COLOR_YELLOW}docker logs -f ${CONTAINER_NAME}${NC}"
    echo -e "   Stop:        ${COLOR_YELLOW}docker stop ${CONTAINER_NAME}${NC}"
    echo -e "   MCP log:     ${COLOR_YELLOW}cat /tmp/docker_mcp_gateway.log${NC}"
else
    echo -e "\n${COLOR_RED}❌ Failed to start Agent-Zero. Check logs:${NC}"
    echo -e "   docker logs ${CONTAINER_NAME}"
    exit 1
fi
