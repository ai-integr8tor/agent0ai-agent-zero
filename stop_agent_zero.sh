#!/bin/bash

# ==============================================================================
# Agent-Zero Stop Script
# ==============================================================================
# Stops running Agent-Zero containers
# ==============================================================================

set -e

# Colors for output
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

# Configuration
NORMAL_CONTAINER="agent-zero-normal"
HACKING_CONTAINER="agent-zero-hacking"
MCP_NETWORK_NAME="agent-zero-mcp-network"
CHROME_MCP_PID_FILE="/tmp/chrome_mcp_server.pid"

show_usage() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  --normal     Stop normal version only"
    echo "  --hacking    Stop hacking version only"
    echo "  --all        Stop both versions (default)"
    echo "  --help       Show this help message"
    echo ""
    echo "Note: MCP bridge network is automatically cleaned up on stop."
    echo ""
    echo "Examples:"
    echo "  $0                    # Stop all and cleanup MCP network"
    echo "  $0 --normal          # Stop normal version only"
    echo "  $0 --hacking         # Stop hacking version only"
}

stop_container() {
    local container_name="$1"
    local version_name="$2"

    if docker ps | grep -q "$container_name"; then
        echo -e "${COLOR_BLUE}🛑 Stopping $version_name...${NC}"
        docker stop "$container_name"
        echo -e "${COLOR_GREEN}✅ $version_name stopped${NC}"
    else
        echo -e "${COLOR_YELLOW}ℹ️  $version_name is not running${NC}"
    fi
}

# Parse command line arguments
STOP_MODE="all"
case "${1:-}" in
    --normal)
        STOP_MODE="normal"
        ;;
    --hacking)
        STOP_MODE="hacking"
        ;;
    --all)
        STOP_MODE="all"
        ;;
    --help)
        show_usage
        exit 0
        ;;
    "")
        STOP_MODE="all"
        ;;
    *)
        echo "Unknown option: $1"
        show_usage
        exit 1
        ;;
esac

echo -e "${COLOR_BLUE}🔍 Checking Agent-Zero containers...${NC}"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${COLOR_RED}Error: Docker is not running.${NC}"
    exit 1
fi

# Stop containers based on mode
case "$STOP_MODE" in
    "normal")
        stop_container "$NORMAL_CONTAINER" "Agent-Zero Normal"
        ;;
    "hacking")
        stop_container "$HACKING_CONTAINER" "Agent-Zero Hacking"
        ;;
    "all")
        stop_container "$NORMAL_CONTAINER" "Agent-Zero Normal"
        stop_container "$HACKING_CONTAINER" "Agent-Zero Hacking"
        ;;
esac

# Cleanup MCP network (always done automatically)
echo -e "\n${COLOR_BLUE}🗑️  Cleaning up MCP bridge network...${NC}"
if docker network ls | grep -q "$MCP_NETWORK_NAME"; then
    # Disconnect any connected containers
    CONNECTED_CONTAINERS=$(docker network inspect "$MCP_NETWORK_NAME" --format='{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "")
    
    if [ -n "$CONNECTED_CONTAINERS" ]; then
        echo -e "${COLOR_YELLOW}⚠️  Disconnecting containers...${NC}"
        for container in $CONNECTED_CONTAINERS; do
            echo -e "   Disconnecting: ${COLOR_YELLOW}${container}${NC}"
            docker network disconnect -f "$MCP_NETWORK_NAME" "$container" 2>/dev/null || true
        done
    fi
    
    # Remove the network
    docker network rm "$MCP_NETWORK_NAME" 2>/dev/null && \
        echo -e "${COLOR_GREEN}✅ MCP network removed${NC}" || \
        echo -e "${COLOR_YELLOW}⚠️  Could not remove MCP network${NC}"
else
    echo -e "${COLOR_YELLOW}ℹ️  MCP network does not exist${NC}"
fi

# Stop Chrome DevTools MCP
echo -e "\n${COLOR_BLUE}🗑️  Stopping Chrome DevTools MCP...${NC}"
if [[ -f "$CHROME_MCP_PID_FILE" ]]; then
    MCP_PID=$(cat "$CHROME_MCP_PID_FILE")
    if ps -p "$MCP_PID" >/dev/null 2>&1; then
        echo -e "${COLOR_YELLOW}⚠️  Stopping MCP server (PID: $MCP_PID)...${NC}"
        kill "$MCP_PID" 2>/dev/null || true
        sleep 2
        echo -e "${COLOR_GREEN}✅ MCP server stopped${NC}"
    fi
    rm -f "$CHROME_MCP_PID_FILE"
else
    pkill -f "mcp.server.*server.py" 2>/dev/null && echo -e "${COLOR_GREEN}✅ Cleaned up MCP processes${NC}" || echo -e "${COLOR_YELLOW}ℹ️  No MCP processes found${NC}"
fi

# Note: Chrome is NOT stopped automatically - user may want to keep it running
echo -e "\n${COLOR_YELLOW}ℹ️  Chrome browser left running (you may want to keep using it)${NC}"
echo -e "${COLOR_BLUE}💡 To stop Chrome: pkill -f 'Google Chrome.*remote-debugging-port'${NC}"

echo -e "\n${COLOR_BLUE}📋 Container Status:${NC}"
if docker ps | grep -q "agent-zero"; then
    echo -e "${COLOR_YELLOW}Still running:${NC}"
    docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" | grep "agent-zero" || true
else
    echo -e "${COLOR_GREEN}✅ No Agent-Zero containers running${NC}"
fi

echo -e "\n${COLOR_BLUE}💡 Useful commands:${NC}"
echo -e "   • Start normal: ${COLOR_YELLOW}./run_agent_zero_normal.sh${NC}"
echo -e "   • Start hacking: ${COLOR_YELLOW}./run_agent_zero_hacking.sh${NC}"
echo -e "   • View all containers: ${COLOR_YELLOW}docker ps -a${NC}"
echo -e "   • Remove stopped containers: ${COLOR_YELLOW}docker container prune${NC}"