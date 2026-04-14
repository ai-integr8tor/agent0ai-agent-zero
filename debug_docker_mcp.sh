#!/bin/bash

# ==============================================================================
# Debug Docker MCP Connection Issues
# ==============================================================================

set -e

CONTAINER_NAME="agent-zero-normal"
MCP_PORT="8813"

echo "🔍 Debugging Docker MCP connection issues..."
echo ""

# Check container status
echo "1️⃣ Container Status:"
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "✅ Container $CONTAINER_NAME is running"
else
    echo "❌ Container $CONTAINER_NAME is not running"
    exit 1
fi

echo ""
echo "2️⃣ Docker CLI in Container:"
if docker exec "$CONTAINER_NAME" which docker >/dev/null 2>&1; then
    echo "✅ Docker CLI is installed"
    DOCKER_VERSION=$(docker exec "$CONTAINER_NAME" docker --version 2>/dev/null || echo "Version check failed")
    echo "📋 Version: $DOCKER_VERSION"
else
    echo "❌ Docker CLI not found"
fi

echo ""
echo "3️⃣ Docker Socket Access:"
if docker exec "$CONTAINER_NAME" test -S /var/run/docker.sock 2>/dev/null; then
    echo "✅ Docker socket is mounted"
    SOCKET_PERMS=$(docker exec "$CONTAINER_NAME" ls -la /var/run/docker.sock 2>/dev/null || echo "Permission check failed")
    echo "📋 Permissions: $SOCKET_PERMS"
else
    echo "❌ Docker socket not found or not mounted"
fi

echo ""
echo "4️⃣ Docker Connectivity:"
if docker exec "$CONTAINER_NAME" docker info >/dev/null 2>&1; then
    echo "✅ Docker can connect to daemon"
else
    echo "❌ Docker cannot connect to daemon"
    echo "🔍 Error details:"
    docker exec "$CONTAINER_NAME" docker info 2>&1 | head -5 || echo "No error details available"
fi

echo ""
echo "5️⃣ MCP Port Status:"
if netstat -an 2>/dev/null | grep -q ":$MCP_PORT "; then
    echo "✅ Port $MCP_PORT is listening"
    netstat -an 2>/dev/null | grep ":$MCP_PORT " || true
else
    echo "❌ Port $MCP_PORT is not listening"
fi

echo ""
echo "6️⃣ Alpine/Socat Test:"
echo "🧪 Testing alpine/socat container directly..."
if docker exec "$CONTAINER_NAME" docker run --rm alpine/socat --version >/dev/null 2>&1; then
    echo "✅ alpine/socat container works"
else
    echo "❌ alpine/socat container fails"
    echo "🔍 Trying to pull alpine/socat..."
    docker exec "$CONTAINER_NAME" docker pull alpine/socat 2>&1 | head -5 || echo "Pull failed"
fi

echo ""
echo "7️⃣ MCP Configuration:"
if docker exec "$CONTAINER_NAME" test -f /a0/tmp/settings.json 2>/dev/null; then
    echo "✅ settings.json exists"
    if docker exec "$CONTAINER_NAME" grep -q "mcp_servers" /a0/tmp/settings.json 2>/dev/null; then
        echo "✅ MCP configuration found"
        echo "📋 MCP Config:"
        docker exec "$CONTAINER_NAME" grep -A 15 "mcp_servers" /a0/tmp/settings.json 2>/dev/null | head -20 || echo "Config extraction failed"
    else
        echo "❌ No MCP configuration found"
    fi
else
    echo "❌ settings.json not found"
fi

echo ""
echo "8️⃣ Manual MCP Test:"
echo "🧪 Testing MCP command manually..."
MCP_TEST_RESULT=$(docker exec "$CONTAINER_NAME" timeout 5s docker run -i --rm alpine/socat STDIO TCP:host.docker.internal:$MCP_PORT 2>&1 || echo "Manual test failed")
if [[ "$MCP_TEST_RESULT" == *"Connection refused"* ]]; then
    echo "❌ Connection refused to port $MCP_PORT"
elif [[ "$MCP_TEST_RESULT" == *"timeout"* ]]; then
    echo "❌ Connection timeout to port $MCP_PORT"
else
    echo "📋 Manual test result: $MCP_TEST_RESULT"
fi

echo ""
echo "🎯 Recommendations:"

if ! docker exec "$CONTAINER_NAME" which docker >/dev/null 2>&1; then
    echo "💡 Reinstall Docker CLI: Stop container and restart"
fi

if ! docker exec "$CONTAINER_NAME" docker info >/dev/null 2>&1; then
    echo "💡 Check Docker socket mount: -v /var/run/docker.sock:/var/run/docker.sock"
fi

if ! netstat -an 2>/dev/null | grep -q ":$MCP_PORT "; then
    echo "💡 Check port mapping: -p $MCP_PORT:$MCP_PORT"
fi

echo "💡 Try manual restart: ./stop_agent_zero.sh && ./run_agent_zero_normal.sh"
echo "💡 Test in browser: http://localhost:50001"