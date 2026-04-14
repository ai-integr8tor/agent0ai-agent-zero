#!/bin/bash

# ==============================================================================
# Test Docker MCP Setup
# ==============================================================================
# This script tests if Docker MCP is properly configured in Agent-Zero
# ==============================================================================

set -e

CONTAINER_NAME="agent-zero-normal"

echo "🔍 Testing Docker MCP setup..."

# Check if container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Container $CONTAINER_NAME is not running"
    echo "💡 Start it with: ./run_agent_zero_normal.sh"
    exit 1
fi

echo "✅ Container is running"

# Check if Docker CLI is installed
if docker exec "$CONTAINER_NAME" which docker >/dev/null 2>&1; then
    echo "✅ Docker CLI is installed in container"
    
    # Check Docker version
    DOCKER_VERSION=$(docker exec "$CONTAINER_NAME" docker --version 2>/dev/null || echo "Unknown")
    echo "📋 Docker version: $DOCKER_VERSION"
    
    # Test Docker connectivity
    if docker exec "$CONTAINER_NAME" docker ps >/dev/null 2>&1; then
        echo "✅ Docker can connect to host daemon"
    else
        echo "❌ Docker CLI cannot connect to host daemon"
        echo "💡 Check Docker socket mount: /var/run/docker.sock"
    fi
else
    echo "❌ Docker CLI not found in container"
    echo "💡 Try restarting with: ./run_agent_zero_normal.sh"
fi

# Check if settings.json has MCP configuration
if docker exec "$CONTAINER_NAME" test -f /a0/tmp/settings.json 2>/dev/null; then
    echo "✅ settings.json exists"
    
    if docker exec "$CONTAINER_NAME" grep -q "mcp_servers" /a0/tmp/settings.json 2>/dev/null; then
        echo "✅ MCP servers configuration found"
        
        if docker exec "$CONTAINER_NAME" grep -q "docker" /a0/tmp/settings.json 2>/dev/null; then
            echo "✅ Docker MCP server configured"
        else
            echo "❌ Docker MCP server not found in configuration"
        fi
    else
        echo "❌ No MCP servers configuration found"
    fi
else
    echo "❌ settings.json not found"
fi

echo ""
echo "📋 Summary:"
echo "  • Container: $CONTAINER_NAME"
echo "  • Web UI: http://localhost:50001"
echo "  • Expected MCP Port: 8813"
echo ""
echo "💡 Test in Agent-Zero web UI:"
echo "  • Ask: 'List my Docker containers'"
echo "  • Ask: 'Show me running Docker processes'"