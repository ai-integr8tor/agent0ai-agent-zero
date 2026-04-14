#!/bin/bash

# ==============================================================================
# Agent-Zero Normal Version Runner
# ==============================================================================
# Runs the standard Agent-Zero with persistence and backup safety
# Includes Docker MCP bridge network setup and teardown
# ==============================================================================

set -e
set -u

# Colors for output
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

# Configuration
CONTAINER_NAME="agent-zero-normal"
IMAGE="agent0ai/agent-zero:latest"
DEFAULT_PORT="50001"
DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/a0"
CHROME_DEBUG_PORT="9222"
MCP_GATEWAY_PORT="8811"   # localhost-only gateway
DOCKER_MCP_PORT="8813"    # socat proxy – reachable from container
MCP_AUTH_TOKEN="agent-zero-mcp-2024"
ENABLE_DOCKER_MCP="true"  # Always enabled
MCP_NETWORK_NAME="agent-zero-mcp-network"
CHROME_MCP_PID_FILE="/tmp/chrome_mcp_server.pid"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--port)
            WEB_UI_PORT="$2"
            shift 2
            ;;
        -d|--data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        --docker-mcp-port)
            DOCKER_MCP_PORT="$2"
            shift 2
            ;;
        --disable-docker-mcp)
            ENABLE_DOCKER_MCP="false"
            shift
            ;;
        --mcp-network)
            MCP_NETWORK_NAME="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-p PORT] [-d DATA_DIR] [--docker-mcp-port PORT] [--disable-docker-mcp]"
            echo ""
            echo "Options:"
            echo "  -p, --port PORT           Set web UI port (default: 50001)"
            echo "  -d, --data-dir DIR        Set data directory (default: ~/agent-zero-data)"
            echo "  --docker-mcp-port PORT    Docker MCP port (default: 8813)"
            echo "  --disable-docker-mcp      Disable Docker MCP toolkit (enabled by default)"
            echo "  --mcp-network NAME        MCP network name (default: agent-zero-mcp-network)"
            echo "  -h, --help                Show this help message"
            echo ""
            echo "Note: Docker MCP toolkit is ENABLED BY DEFAULT"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run with defaults (Docker MCP enabled)"
            echo "  $0 -p 50002                          # Run on port 50002 (Docker MCP enabled)"
            echo "  $0 -d /path/to/data                   # Use custom data directory (Docker MCP enabled)"
            echo "  $0 --docker-mcp-port 8814            # Custom MCP port"
            echo "  $0 --disable-docker-mcp               # Disable Docker MCP toolkit"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set defaults if not provided
WEB_UI_PORT="${WEB_UI_PORT:-$DEFAULT_PORT}"

# Pre-flight checks
if ! command -v docker &> /dev/null; then
    echo -e "${COLOR_RED}Error: Docker not found. Please install Docker Desktop.${NC}"
    exit 1
fi

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${COLOR_RED}Error: Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

# Create data directory
echo -e "${COLOR_BLUE}📁 Setting up data directory...${NC}"
mkdir -p "${DATA_DIR}"

# Check for Chrome debug port conflicts if Docker MCP is enabled
if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
    if lsof -i ":${CHROME_DEBUG_PORT}" >/dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✅ Chrome already running on debug port ${CHROME_DEBUG_PORT}${NC}"
    fi
fi

# Check if container is already running
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${COLOR_YELLOW}⚠️  Container '$CONTAINER_NAME' is already running.${NC}"
    echo "Stop it with: ./stop_agent_zero.sh --normal"
    exit 1
fi

# Remove existing stopped container
if docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo -e "${COLOR_YELLOW}🗑️  Removing existing container...${NC}"
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1
fi


# --- Kill stale MCP gateway + socat, then start fresh ---
echo -e "${COLOR_BLUE}🔄 Cleaning up old MCP gateway processes...${NC}"
pkill -f "docker-mcp.*gateway run.*${MCP_GATEWAY_PORT}" 2>/dev/null || true
pkill -f "docker mcp gateway run.*${MCP_GATEWAY_PORT}" 2>/dev/null || true
pkill -f "socat.*${DOCKER_MCP_PORT}" 2>/dev/null || true
sleep 2

echo -e "${COLOR_BLUE}🐳 Starting Docker MCP Gateway on port ${MCP_GATEWAY_PORT}...${NC}"
export MCP_GATEWAY_AUTH_TOKEN="${MCP_AUTH_TOKEN}"
nohup bash -c "export MCP_GATEWAY_AUTH_TOKEN='${MCP_AUTH_TOKEN}'; \\
    docker mcp gateway run \\
        --transport sse \\
        --port ${MCP_GATEWAY_PORT} \\
        --servers docker \\
        --long-lived \\
        --static \\
    > /tmp/docker_mcp_gateway.log 2>&1" &
for i in {1..30}; do
    if lsof -i ":${MCP_GATEWAY_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
        sleep 3
        echo -e "${COLOR_GREEN}  ✅ MCP Gateway up on port ${MCP_GATEWAY_PORT}${NC}"
        break
    fi
    sleep 1
done

echo -e "${COLOR_BLUE}🔀 Starting socat proxy 0.0.0.0:${DOCKER_MCP_PORT} -> 127.0.0.1:${MCP_GATEWAY_PORT}...${NC}"
if command -v socat &>/dev/null; then
    nohup socat TCP-LISTEN:${DOCKER_MCP_PORT},bind=0.0.0.0,reuseaddr,fork \
        TCP:127.0.0.1:${MCP_GATEWAY_PORT} \
        > /tmp/socat_mcp_proxy.log 2>&1 &
    sleep 1
    if lsof -i ":${DOCKER_MCP_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
        echo -e "${COLOR_GREEN}  ✅ Socat proxy up on port ${DOCKER_MCP_PORT}${NC}"
    else
        echo -e "${COLOR_RED}  ❌ Socat proxy failed (brew install socat)${NC}"
    fi
else
    echo -e "${COLOR_RED}  ❌ socat not found. Run: brew install socat${NC}"
fi

# Copy chrome_mcp_server.py into a0/ so /a0/chrome_mcp_server.py works in container
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${DATA_DIR}"
[ -f "${SCRIPT_ROOT}/chrome_mcp_server.py" ] && cp "${SCRIPT_ROOT}/chrome_mcp_server.py" "${DATA_DIR}/chrome_mcp_server.py"

# Pre-configure MCP servers in settings.json before container starts
if [ -f "${SCRIPT_ROOT}/docker_mcp_config.json" ] && [ -f "${DATA_DIR}/usr/settings.json" ]; then
    echo -e "${COLOR_BLUE}🔧 Pre-configuring MCP servers in settings.json...${NC}"
    python3 - <<EOF
import json
settings_path = "${DATA_DIR}/usr/settings.json"
mcp_config_path = "${SCRIPT_ROOT}/docker_mcp_config.json"
with open(settings_path) as f:
    settings = json.load(f)
with open(mcp_config_path) as f:
    mcp_config = json.load(f)
# Merge: keep user-added servers, update/add docker_mcp_config entries
existing = json.loads(settings.get("mcp_servers", "{}"))
merged = existing.get("mcpServers", {}).copy()
merged.update(mcp_config.get("mcpServers", {}))
settings["mcp_servers"] = json.dumps({"mcpServers": merged}, indent=4)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=4)
print("  MCP servers: " + ", ".join(merged.keys()))
EOF
fi

# Pull latest image
echo -e "${COLOR_BLUE}📥 Pulling latest image...${NC}"
docker pull "$IMAGE"

# Start Chrome DevTools MCP if enabled
if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
    echo -e "${COLOR_BLUE}🐍 Setting up Chrome DevTools MCP...${NC}"
    
    # Check if Chrome debug port is already in use on host
    if lsof -i ":${CHROME_DEBUG_PORT}" >/dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✅ Chrome already running with debug port ${CHROME_DEBUG_PORT}${NC}"
    else
        # Start Chrome with remote debugging on host
        CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        USER_DATA_DIR="$HOME/Library/Application Support/Google/Chrome-DevTools-MCP"
        
        if [ ! -f "$CHROME_PATH" ]; then
            echo -e "${COLOR_RED}❌ Chrome not found at: $CHROME_PATH${NC}"
            echo -e "${COLOR_YELLOW}💡 Please install Google Chrome${NC}"
        else
            echo -e "${COLOR_BLUE}🌐 Starting Chrome with remote debugging on port ${CHROME_DEBUG_PORT}...${NC}"
            mkdir -p "$USER_DATA_DIR"
            "$CHROME_PATH" \
                --remote-debugging-port=${CHROME_DEBUG_PORT} \
                --remote-debugging-address=0.0.0.0 \
                --user-data-dir="$USER_DATA_DIR" \
                --no-first-run \
                --no-default-browser-check \
                --disable-background-networking \
                --disable-default-apps \
                --disable-extensions \
                --disable-sync \
                --disable-translate \
                --hide-scrollbars \
                --metrics-recording-only \
                --mute-audio \
                --safebrowsing-disable-auto-update \
                --disable-features=TranslateUI \
                >/tmp/chrome_debug.log 2>&1 &
            CHROME_PID=$!
            echo -e "${COLOR_GREEN}✅ Chrome started on host (PID: ${CHROME_PID})${NC}"
            sleep 3
            
            # Verify Chrome debug port is open
            if lsof -i :${CHROME_DEBUG_PORT} >/dev/null 2>&1; then
                echo -e "${COLOR_GREEN}✅ Chrome debug port ${CHROME_DEBUG_PORT} is open${NC}"
            else
                echo -e "${COLOR_RED}❌ Chrome debug port not open${NC}"
                echo -e "${COLOR_YELLOW}💡 Check logs: cat /tmp/chrome_debug.log${NC}"
            fi
        fi
    fi
fi

echo -e "\n${COLOR_GREEN}=== Starting Agent-Zero (Normal Version) ===${NC}"
echo -e "Image: ${COLOR_YELLOW}${IMAGE}${NC}"
echo -e "Container: ${COLOR_YELLOW}${CONTAINER_NAME}${NC}"
echo -e "Access URL: ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
echo -e "Data Directory: ${COLOR_YELLOW}${DATA_DIR}${NC}"
echo -e "${COLOR_GREEN}Starting container...${NC}\n"

# Build Docker run command with Docker CLI and MCP support
DOCKER_ARGS=(
  "-d"
  "--name" "$CONTAINER_NAME"
  "-p" "$WEB_UI_PORT:80"
  "--add-host=host.docker.internal:host-gateway"
  "-v" "/var/run/docker.sock:/var/run/docker.sock"
  "-v" "${DATA_DIR}:/a0"
)

# Run the container with /a0/usr mount (official recommendation — do NOT mount full /a0)
CONTAINER_ID=$(docker run "${DOCKER_ARGS[@]}" "$IMAGE")

# Wait for container to be ready and initial apt processes to settle
echo -e "${COLOR_BLUE}⏳ Waiting for container to be ready...${NC}"
sleep 10

# Wait for any initial apt processes in the container to finish
echo -e "${COLOR_BLUE}⏳ Waiting for container initialization to complete...${NC}"
docker exec "$CONTAINER_NAME" bash -c "
  # Wait up to 60 seconds for apt locks to be released
  for i in {1..30}; do
    if ! fuser /var/lib/apt/lists/lock >/dev/null 2>&1 && ! fuser /var/lib/dpkg/lock >/dev/null 2>&1; then
      echo 'Container initialization complete'
      break
    fi
    echo 'Waiting for container initialization... (\$i/30)'
    sleep 2
  done
"

# Auto-configure MCP if enabled
if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
  echo -e "${COLOR_BLUE}🔧 Auto-configuring MCP servers...${NC}"
  ./auto_configure_docker_mcp.sh "$CONTAINER_NAME" "$CHROME_DEBUG_PORT" "$DOCKER_MCP_PORT" "$MCP_AUTH_TOKEN"
fi

# Wait for Agent-Zero to fully start
echo -e "${COLOR_BLUE}⏳ Waiting for Agent-Zero to start...${NC}"
sleep 10

# Check if container is running
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "\n${COLOR_GREEN}✅ Agent-Zero is running successfully!${NC}"
    echo -e "🌐 Access the web UI at: ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
    echo -e "📁 Your data is persisted in: ${COLOR_YELLOW}${DATA_DIR}${NC}"
    if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
        echo -e "🌐 Chrome DevTools MCP enabled (controls Chrome on your Mac)"
    fi
    echo -e "\n${COLOR_BLUE}💡 Important reminders:${NC}"
    echo -e "   • Configure your API keys in Settings"
    echo -e "   • Create regular backups via Settings → Backup & Restore"
    echo -e "   • Your data persists between restarts"
    if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
        echo -e "   • Chrome MCP server is AUTO-CONFIGURED"
        echo -e "   • Test with: 'Navigate to google.com'"
    fi
    echo -e "\n${COLOR_BLUE}📋 Useful commands:${NC}"
    echo -e "   • View logs: ${COLOR_YELLOW}docker logs -f $CONTAINER_NAME${NC}"
    echo -e "   • Stop container: ${COLOR_YELLOW}docker stop $CONTAINER_NAME${NC}"
    echo -e "   • Restart: ${COLOR_YELLOW}docker restart $CONTAINER_NAME${NC}"
else
    echo -e "\n${COLOR_RED}❌ Failed to start Agent-Zero${NC}"
    echo "Check the logs with: docker logs $CONTAINER_NAME"
    exit 1
fi