#!/bin/bash

# ==============================================================================
# Simple Docker MCP Configuration
# ==============================================================================
# Uses direct Docker CLI access instead of socat tunneling
# ==============================================================================

CONTAINER_NAME="agent-zero-normal"

echo "🔧 Configuring simple Docker MCP access..."

# Create a simple Docker MCP configuration that just uses Docker CLI directly
docker exec "$CONTAINER_NAME" python3 -c "
import json
import sys
import os

os.chdir('/a0/tmp')

# Read current settings
try:
    with open('settings.json', 'r') as f:
        settings = json.load(f)
except:
    settings = {}

# Create simple Docker MCP configuration
# Instead of socat, we'll just use Docker CLI directly
mcp_config = []

# Since Agent-Zero has Docker CLI installed and socket access,
# we don't need MCP for basic Docker operations.
# Agent-Zero can use Docker directly through its code execution capabilities.

# Set empty MCP servers (Agent-Zero will use Docker via code execution)
settings['mcp_servers'] = json.dumps(mcp_config)

# Write updated settings
with open('settings.json', 'w') as f:
    json.dump(settings, f, indent=2)

print('✅ Docker MCP configuration updated - using direct Docker access')
"

echo "✅ Docker MCP configured for direct access"
echo "💡 Agent-Zero can now use Docker via:"
echo "   • Ask: 'Run the docker ps command'"
echo "   • Ask: 'Execute: docker images'"
echo "   • Ask: 'Show me my running containers using docker'"