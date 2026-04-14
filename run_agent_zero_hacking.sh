#!/bin/bash

# ==============================================================================
# Agent-Zero Hacking Version Runner
# ==============================================================================
# Runs the hacking edition of Agent-Zero with cybersecurity tools
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
CONTAINER_NAME="agent-zero-hacking"
IMAGE="agent0ai/agent-zero:hacking"
DEFAULT_PORT="50002"
DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/a0-hacking"
CHROME_DEBUG_PORT="9223"          # hacking uses 9223 to avoid clash with normal (9222)
MCP_GATEWAY_PORT="8811"           # localhost-only gateway (shared with normal script)
DOCKER_MCP_PORT="8814"            # socat proxy for hacking container (8813 used by normal)
MCP_AUTH_TOKEN="agent-zero-mcp-2024"
ENABLE_DOCKER_MCP="true"          # Always enabled
CHROME_MCP_PID_FILE="/tmp/chrome_mcp_server_hacking.pid"

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
        -h|--help)
            echo "Usage: $0 [-p PORT] [-d DATA_DIR] [--docker-mcp-port PORT] [--disable-docker-mcp]"
            echo ""
            echo "Options:"
            echo "  -p, --port PORT           Set web UI port (default: 50002)"
            echo "  -d, --data-dir DIR        Set data directory (default: ./a0-hacking)"
            echo "  --docker-mcp-port PORT    Docker MCP port (default: 8814)"
            echo "  --disable-docker-mcp      Disable Docker MCP toolkit (enabled by default)"
            echo "  -h, --help                Show this help message"
            echo ""
            echo "Note: Docker MCP toolkit is ENABLED BY DEFAULT"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run with defaults (Docker MCP enabled)"
            echo "  $0 -p 50003                          # Run on port 50003 (Docker MCP enabled)"
            echo "  $0 -d /path/to/data                   # Use custom data directory (Docker MCP enabled)"
            echo "  $0 --docker-mcp-port 8815            # Custom MCP port"
            echo "  $0 --disable-docker-mcp               # Disable Docker MCP toolkit"
            echo ""
            echo "⚠️  WARNING: This is the HACKING edition with cybersecurity tools."
            echo "    Use responsibly and only on systems you own or have permission to test."
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

# Security warning
echo -e "${COLOR_RED}⚠️  SECURITY WARNING ⚠️${NC}"
echo -e "${COLOR_YELLOW}You are starting the HACKING edition of Agent-Zero.${NC}"
echo -e "${COLOR_YELLOW}This version includes cybersecurity and penetration testing tools.${NC}"
echo -e "${COLOR_YELLOW}Use ONLY on systems you own or have explicit permission to test.${NC}"
echo ""
read -p "Do you understand and accept responsibility? (yes/no): " response
if [[ ! "$response" =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Aborted."
    exit 1
fi

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
echo -e "${COLOR_BLUE}📁 Setting up hacking data directory...${NC}"
mkdir -p "${DATA_DIR}"

# Check if container is already running
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${COLOR_YELLOW}⚠️  Container '$CONTAINER_NAME' is already running.${NC}"
    echo "Stop it with: docker stop $CONTAINER_NAME"
    exit 1
fi

# Remove existing stopped container
if docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo -e "${COLOR_YELLOW}🗑️  Removing existing container...${NC}"
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1
fi

# --- Kill stale socat for hacking port, then start fresh ---
echo -e "${COLOR_BLUE}🔄 Cleaning up old MCP socat proxy for hacking...${NC}"
pkill -f "socat.*${DOCKER_MCP_PORT}" 2>/dev/null || true
sleep 1

# Check if MCP gateway is already running (shared with normal script)
if ! lsof -i ":${MCP_GATEWAY_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
    echo -e "${COLOR_BLUE}🐳 Starting Docker MCP Gateway on port ${MCP_GATEWAY_PORT}...${NC}"
    export MCP_GATEWAY_AUTH_TOKEN="${MCP_AUTH_TOKEN}"
    nohup bash -c "export MCP_GATEWAY_AUTH_TOKEN='${MCP_AUTH_TOKEN}'; \
        docker mcp gateway run \
            --transport sse \
            --port ${MCP_GATEWAY_PORT} \
            --servers docker \
            --long-lived \
            --static \
        > /tmp/docker_mcp_gateway.log 2>&1" &
    for i in {1..30}; do
        if lsof -i ":${MCP_GATEWAY_PORT}" -n -P 2>/dev/null | grep -q LISTEN; then
            sleep 3
            echo -e "${COLOR_GREEN}  ✅ MCP Gateway up on port ${MCP_GATEWAY_PORT}${NC}"
            break
        fi
        sleep 1
    done
else
    echo -e "${COLOR_GREEN}  ✅ MCP Gateway already running on port ${MCP_GATEWAY_PORT}${NC}"
fi

echo -e "${COLOR_BLUE}🔀 Starting socat proxy 0.0.0.0:${DOCKER_MCP_PORT} -> 127.0.0.1:${MCP_GATEWAY_PORT}...${NC}"
if command -v socat &>/dev/null; then
    nohup socat TCP-LISTEN:${DOCKER_MCP_PORT},bind=0.0.0.0,reuseaddr,fork \
        TCP:127.0.0.1:${MCP_GATEWAY_PORT} \
        > /tmp/socat_mcp_proxy_hacking.log 2>&1 &
    sleep 1
    lsof -i ":${DOCKER_MCP_PORT}" -n -P 2>/dev/null | grep -q LISTEN \
        && echo -e "${COLOR_GREEN}  ✅ Socat proxy up on port ${DOCKER_MCP_PORT}${NC}" \
        || echo -e "${COLOR_RED}  ❌ Socat proxy failed${NC}"
else
    echo -e "${COLOR_RED}  ❌ socat not found. Run: brew install socat${NC}"
fi

# Copy chrome_mcp_server.py into a0-hacking/ so /a0/chrome_mcp_server.py works in container
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${DATA_DIR}"
[ -f "${SCRIPT_ROOT}/chrome_mcp_server.py" ] && cp "${SCRIPT_ROOT}/chrome_mcp_server.py" "${DATA_DIR}/chrome_mcp_server.py"

# Pull latest hacking image
echo -e "${COLOR_BLUE}📥 Pulling latest hacking image...${NC}"
docker pull "$IMAGE"

echo -e "\n${COLOR_RED}=== Starting Agent-Zero (🔴 HACKING EDITION 🔴) ===${NC}"
echo -e "Image: ${COLOR_YELLOW}${IMAGE}${NC}"
echo -e "Container: ${COLOR_YELLOW}${CONTAINER_NAME}${NC}"
echo -e "Access URL: ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
echo -e "Data Directory: ${COLOR_YELLOW}${DATA_DIR}${NC}"
echo -e "${COLOR_RED}⚠️  CYBERSECURITY TOOLS ENABLED ⚠️${NC}"
echo -e "${COLOR_GREEN}Starting container...${NC}\n"

# Build Docker run command with optional MCP support
DOCKER_ARGS=(
  "-d"
  "--name" "$CONTAINER_NAME"
  "-p" "$WEB_UI_PORT:80"
  "--add-host=host.docker.internal:host-gateway"
  "--privileged"
  "--cap-add=ALL"
  "-v" "/var/run/docker.sock:/var/run/docker.sock"
  "-v" "${DATA_DIR}:/a0"
)

# Run the container with selective directory mapping (hybrid approach)
# Note: Hacking edition needs additional privileges for security tools
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
echo -e "${COLOR_BLUE}⏳ Waiting for Agent-Zero Hacking Edition to start...${NC}"
sleep 10

# Check if container is running
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "\n${COLOR_GREEN}✅ Agent-Zero Hacking Edition is running successfully!${NC}"
    echo -e "🌐 Access the web UI at: ${COLOR_YELLOW}http://localhost:${WEB_UI_PORT}${NC}"
    echo -e "📁 Your data is persisted in: ${COLOR_YELLOW}${DATA_DIR}${NC}"
    if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
        echo -e "🐳 Docker MCP toolkit enabled on port: ${COLOR_YELLOW}${DOCKER_MCP_PORT}${NC}"
        echo -e "🔧 Docker MCP auto-configured via socat proxy"
    fi
    echo -e "\n${COLOR_RED}🔒 Security reminders:${NC}"
    echo -e "   • This version has elevated privileges for security tools"
    echo -e "   • Use only for legitimate cybersecurity testing"
    echo -e "   • Data is isolated from the normal version"
    echo -e "   • Configure your API keys in Settings"
    echo -e "   • Create regular backups via Settings → Backup & Restore"
    if [[ "${ENABLE_DOCKER_MCP}" == "true" ]]; then
        echo -e "   • Docker MCP server is AUTO-CONFIGURED (no manual setup needed)"
        echo -e "   • Test with: 'List my Docker containers'"
    fi
    echo -e "\n${COLOR_BLUE}📋 Useful commands:${NC}"
    echo -e "   • View logs: ${COLOR_YELLOW}docker logs -f $CONTAINER_NAME${NC}"
    echo -e "   • Stop container: ${COLOR_YELLOW}docker stop $CONTAINER_NAME${NC}"
    echo -e "   • Restart: ${COLOR_YELLOW}docker restart $CONTAINER_NAME${NC}"
else
    echo -e "\n${COLOR_RED}❌ Failed to start Agent-Zero Hacking Edition${NC}"
    echo "Check the logs with: docker logs $CONTAINER_NAME"
    exit 1
fi
