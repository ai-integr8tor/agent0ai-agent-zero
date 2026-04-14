#!/bin/bash

# ==============================================================================
# Test Docker MCP Connection
# ==============================================================================

CONTAINER_NAME="$1"

if [[ -z "$CONTAINER_NAME" ]]; then
    echo "Usage: $0 <container_name>"
    exit 1
fi

echo "🔍 Testing Docker MCP connection from inside container..."

# Test 1: Check if docker command works
echo -e "\n${COLOR_BLUE}Test 1: Docker CLI availability${NC}"
docker exec "$CONTAINER_NAME" docker --version && echo "✅ Docker CLI available" || echo "❌ Docker CLI not available"

# Test 2: Test socat connection
echo -e "\n${COLOR_BLUE}Test 2: Socat connection to host.docker.internal:8811${NC}"
docker exec "$CONTAINER_NAME" sh -c "
echo '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}' | 
timeout 2 docker run -i --rm --add-host=host.docker.internal:host-gateway alpine/socat STDIO TCP:host.docker.internal:8811 2>&1
" || echo "❌ Socat connection failed"

# Test 3: Check host.docker.internal resolution
echo -e "\n${COLOR_BLUE}Test 3: host.docker.internal resolution${NC}"
docker exec "$CONTAINER_NAME" sh -c "
getent hosts host.docker.internal || echo 'Could not resolve host.docker.internal'
"

# Test 4: Check current settings
echo -e "\n${COLOR_BLUE}Test 4: Current MCP settings${NC}"
docker exec "$CONTAINER_NAME" cat /a0/tmp/settings.json 2>/dev/null || echo "❌ settings.json not found"

echo -e "\n✅ Tests complete"
