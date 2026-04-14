#!/bin/bash

# ==============================================================================
# Docker MCP Bridge Network Setup
# ==============================================================================
# Creates and manages a Docker bridge network for MCP communication
# between Agent-Zero containers and the host machine
# ==============================================================================

set -e

# Configuration
MCP_NETWORK_NAME="agent-zero-mcp-network"
MCP_PORT="${1:-8811}"

# Colors for output
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

show_usage() {
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  create     Create the MCP bridge network"
    echo "  remove     Remove the MCP bridge network"
    echo "  status     Show network status"
    echo "  test       Test connectivity to host"
    echo "  help       Show this help message"
    echo ""
    echo "Options:"
    echo "  PORT       MCP port number (default: 8811)"
    echo ""
    echo "Examples:"
    echo "  $0 create              # Create network with default port"
    echo "  $0 create 8813         # Create network with custom port"
    echo "  $0 remove              # Remove network"
    echo "  $0 status              # Show network status"
    echo "  $0 test                # Test host connectivity"
}

create_network() {
    echo -e "${COLOR_BLUE}🌐 Creating Docker MCP bridge network...${NC}"
    
    # Check if network already exists
    if docker network ls | grep -q "$MCP_NETWORK_NAME"; then
        echo -e "${COLOR_YELLOW}⚠️  Network '$MCP_NETWORK_NAME' already exists${NC}"
        echo -e "${COLOR_BLUE}ℹ️  Removing existing network first...${NC}"
        docker network rm "$MCP_NETWORK_NAME" 2>/dev/null || true
    fi
    
    # Create the bridge network
    docker network create \
        --driver bridge \
        --subnet 172.28.0.0/16 \
        --opt "com.docker.network.bridge.name"="a0-mcp-br0" \
        "$MCP_NETWORK_NAME"
    
    echo -e "${COLOR_GREEN}✅ MCP bridge network created successfully${NC}"
    echo -e "${COLOR_BLUE}📋 Network Details:${NC}"
    echo -e "   Name: ${COLOR_YELLOW}${MCP_NETWORK_NAME}${NC}"
    echo -e "   Subnet: ${COLOR_YELLOW}172.28.0.0/16${NC}"
    echo -e "   Bridge: ${COLOR_YELLOW}a0-mcp-br0${NC}"
    echo -e "   MCP Port: ${COLOR_YELLOW}${MCP_PORT}${NC}"
    
    # Verify host.docker.internal resolution
    echo -e "\n${COLOR_BLUE}🔍 Testing host.docker.internal resolution...${NC}"
    if docker run --rm --network host alpine ping -c 1 host.docker.internal >/dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✅ host.docker.internal is reachable${NC}"
    else
        echo -e "${COLOR_YELLOW}⚠️  host.docker.internal may not be reachable${NC}"
        echo -e "${COLOR_BLUE}ℹ️  This is normal on some systems - using gateway routing${NC}"
    fi
}

remove_network() {
    echo -e "${COLOR_BLUE}🗑️  Removing Docker MCP bridge network...${NC}"
    
    # Check if network exists
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
        docker network rm "$MCP_NETWORK_NAME"
        echo -e "${COLOR_GREEN}✅ MCP bridge network removed${NC}"
    else
        echo -e "${COLOR_YELLOW}ℹ️  Network '$MCP_NETWORK_NAME' does not exist${NC}"
    fi
}

show_status() {
    echo -e "${COLOR_BLUE}📊 Docker MCP Bridge Network Status${NC}"
    echo "============================================"
    
    # Check if network exists
    if docker network ls | grep -q "$MCP_NETWORK_NAME"; then
        echo -e "${COLOR_GREEN}● Network: ${MCP_NETWORK_NAME}${NC}"
        
        # Show network details
        echo -e "\n${COLOR_BLUE}Network Details:${NC}"
        docker network inspect "$MCP_NETWORK_NAME" --format='
Subnet: {{range .IPAM.Config}}{{.Subnet}}{{end}}
Gateway: {{range .IPAM.Config}}{{.Gateway}}{{end}}
Connected Containers: {{range .Containers}}{{.Name}} ({{.IPv4Address}}) {{end}}'
        
        # Show connected containers
        echo -e "\n${COLOR_BLUE}Connected Containers:${NC}"
        docker network inspect "$MCP_NETWORK_NAME" --format='{{range .Containers}}  • {{.Name}} - {{.IPv4Address}}{{end}}' || echo "  None"
    else
        echo -e "${COLOR_YELLOW}○ Network: ${MCP_NETWORK_NAME} (not created)${NC}"
    fi
    
    echo -e "\n${COLOR_BLUE}MCP Port Configuration:${NC}"
    echo -e "  Port: ${COLOR_YELLOW}${MCP_PORT}${NC}"
    
    # Check if port is in use on host
    if lsof -i ":${MCP_PORT}" >/dev/null 2>&1; then
        echo -e "  Status: ${COLOR_GREEN}Active (in use)${NC}"
        echo -e "  Process: $(lsof -i :${MCP_PORT} | tail -n 1 | awk '{print $1}')"
    else
        echo -e "  Status: ${COLOR_YELLOW}Available (not in use)${NC}"
    fi
}

test_connectivity() {
    echo -e "${COLOR_BLUE}🔍 Testing Docker MCP connectivity...${NC}"
    
    # Test 1: host.docker.internal resolution
    echo -e "\n${COLOR_BLUE}Test 1: host.docker.internal resolution${NC}"
    if docker run --rm --network host alpine nslookup host.docker.internal 2>/dev/null | grep -A1 "Name:"; then
        echo -e "${COLOR_GREEN}✅ Resolution successful${NC}"
    else
        echo -e "${COLOR_RED}❌ Resolution failed${NC}"
    fi
    
    # Test 2: Gateway connectivity
    echo -e "\n${COLOR_BLUE}Test 2: Gateway connectivity${NC}"
    if docker run --rm --network "$MCP_NETWORK_NAME" alpine ping -c 1 172.28.0.1 >/dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✅ Gateway reachable${NC}"
    else
        echo -e "${COLOR_YELLOW}⚠️  Gateway not reachable (network may not exist)${NC}"
    fi
    
    # Test 3: MCP port availability
    echo -e "\n${COLOR_BLUE}Test 3: MCP port ${MCP_PORT} availability${NC}"
    if lsof -i ":${MCP_PORT}" >/dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✅ Port ${MCP_PORT} is open on host${NC}"
    else
        echo -e "${COLOR_YELLOW}⚠️  Port ${MCP_PORT} is not in use on host${NC}"
        echo -e "${COLOR_BLUE}ℹ️  This is expected if no MCP server is running${NC}"
    fi
    
    echo -e "\n${COLOR_BLUE}Summary:${NC}"
    echo -e "  For Docker MCP to work, you need:"
    echo -e "  1. ✅ Docker socket mounted in Agent-Zero container"
    echo -e "  2. ✅ host.docker.internal resolvable"
    echo -e "  3. ✅ MCP server running on host port ${MCP_PORT} (or use direct Docker CLI)"
}

# Main command handler
case "${1:-help}" in
    create)
        create_network
        ;;
    remove)
        remove_network
        ;;
    status)
        show_status
        ;;
    test)
        test_connectivity
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        echo -e "${COLOR_RED}❌ Unknown command: $1${NC}"
        show_usage
        exit 1
        ;;
esac
