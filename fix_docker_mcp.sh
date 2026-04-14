#!/bin/bash

# ==============================================================================
# Fix Docker MCP Configuration  
# ==============================================================================
# The issue is that we're trying to connect to a non-existent MCP server
# We need to configure it differently for direct Docker access
# ==============================================================================

set -e

CONTAINER_NAME="agent-zero-normal"

echo "🔧 Fixing Docker MCP configuration..."

# The correct approach is to give Agent-Zero direct access to Docker
# rather than using socat to connect to a non-existent MCP server

# Update the MCP configuration to use Docker directly
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

# Create direct Docker MCP configuration (no socat needed)
mcp_config = [
    {
        'name': 'docker',
        'description': 'Docker container management via direct CLI access',
        'type': 'stdio',
        'command': 'python3',
        'args': ['-c', '''
import subprocess
import sys
import json

def run_docker_command(args):
    try:
        result = subprocess.run([\"docker\"] + args, capture_output=True, text=True)
        return {\"stdout\": result.stdout, \"stderr\": result.stderr, \"returncode\": result.returncode}
    except Exception as e:
        return {\"error\": str(e)}

# Simple MCP-like interface for Docker commands
while True:
    try:
        line = input()
        if not line.strip():
            continue
        cmd = json.loads(line)
        if cmd.get(\"method\") == \"tools/call\" and cmd.get(\"params\", {}).get(\"name\") == \"docker_command\":
            args = cmd.get(\"params\", {}).get(\"arguments\", {}).get(\"args\", [])
            result = run_docker_command(args)
            print(json.dumps({\"result\": result}))
        else:
            print(json.dumps({\"error\": \"Unknown command\"}))
    except EOFError:
        break
    except Exception as e:
        print(json.dumps({\"error\": str(e)}))
'''],
        'disabled': False
    }
]

# Update settings
settings['mcp_servers'] = json.dumps(mcp_config)

# Write updated settings
with open('settings.json', 'w') as f:
    json.dump(settings, f, indent=2)

print('✅ Docker MCP configuration updated for direct access')
"

echo "✅ Docker MCP fixed - now using direct Docker CLI access"
echo "🔄 You may need to restart Agent-Zero for changes to take effect"
echo "💡 Test with: 'List my Docker containers' or 'docker ps'"