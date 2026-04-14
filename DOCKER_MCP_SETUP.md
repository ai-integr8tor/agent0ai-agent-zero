# Chrome DevTools MCP - Agent-Zero

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ YOUR MAC (Host)                                         │
│                                                         │
│  ┌─────────────────┐                                   │
│  │ Chrome Browser  │                                   │
│  │ Port 9222       │                                   │
│  │ (Debug Mode)    │                                   │
│  └────────┬────────┘                                   │
│           │ CDP over WebSocket                          │
│           │ host.docker.internal:9222                   │
└───────────┼─────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│ DOCKER CONTAINER (Agent-Zero)                           │
│                                                         │
│  ┌─────────────────┐     ┌──────────────────┐          │
│  │ Agent-Zero      │────▶│ Chrome MCP Server│          │
│  │ MCP Client      │     │ (Python)         │          │
│  │                 │     │ - navigate       │          │
│  │                 │     │ - screenshot     │          │
│  │                 │     │ - click          │          │
│  │                 │     │ - type           │          │
│  │                 │     │ - evaluate JS    │          │
│  └─────────────────┘     └──────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Start Chrome + Agent-Zero
./run_agent_zero_normal.sh

# Stop Agent-Zero (Chrome stays running)
./stop_agent_zero.sh
```

## How It Works

1. **Chrome runs on your Mac** with remote debugging enabled (port 9222)
2. **Agent-Zero container** has a Python MCP server (`/a0/chrome_mcp_server.py`)
3. **Container connects to host Chrome** via `host.docker.internal:9222`
4. **CDP commands** are sent over WebSocket to control Chrome

## Configuration

### docker_mcp_config.json
```json
{
  "mcpServers": {
    "docker-mcp-toolkit": {
      "name": "docker-mcp-toolkit",
      "description": "Docker MCP Toolkit - Control Docker from the container (SSE)",
      "type": "sse",
      "url": "http://host.docker.internal:8813/sse",
      "disabled": false
    },
    "chrome-devtools": {
      "name": "chrome-devtools",
      "description": "Chrome DevTools - Controls Chrome on your Mac",
      "type": "stdio",
      "command": "python3",
      "args": ["/a0/chrome_mcp_server.py"],
      "env": {
        "CHROME_DEBUG_PORT": "9222",
        "CHROME_HOST": "host.docker.internal"
      },
      "disabled": false
    }
  }
}
```

## Available Tools

- `navigate(url)` - Navigate to a URL
- `screenshot()` - Take a screenshot
- `get_html()` - Get page HTML
- `click(selector)` - Click an element
- `type_text(selector, text)` - Type into input
- `evaluate_javascript(expression)` - Run JS
- `get_console_logs()` - Get console logs

## Example Usage

In Agent-Zero UI:

```
- "Navigate to google.com"
- "Take a screenshot"
- "Click the search button"
- "Type 'hello' into the search box"
- "Get the page HTML"
- "Run document.title in the console"
```

## Manual Setup

### 1. Start Chrome with Debug Port

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome-DevTools-MCP"
```

### 2. Start Agent-Zero

```bash
./run_agent_zero_normal.sh
```

The script will:
- Start Chrome if not running
- Copy MCP server to container
- Install Python dependencies
- Configure MCP settings

## Troubleshooting

### Chrome not starting
```bash
# Check if Chrome is installed
ls -la "/Applications/Google Chrome.app"

# Check if port 9222 is in use
lsof -i :9222
```

### Container can't connect to Chrome
```bash
# Test connection from container
docker exec agent-zero-normal \
  curl -s http://host.docker.internal:9222/json/version

# Should return Chrome version info
```

### MCP server errors
```bash
# Check container logs
docker logs agent-zero-normal 2>&1 | grep -i mcp

# Check MCP server in container
docker exec agent-zero-normal python3 /a0/chrome_mcp_server.py --help
```

### Reset everything
```bash
# Stop Agent-Zero
./stop_agent_zero.sh

# Kill Chrome
pkill -f "Google Chrome.*remote-debugging-port"

# Start fresh
./run_agent_zero_normal.sh
```

## Important Notes

- **Chrome runs on YOUR computer** - not in the container
- **Container connects via host.docker.internal** - Docker's host gateway
- **Chrome stays running** when you stop Agent-Zero
- **Multiple agents** can use the same Chrome instance
- **No automation detection** - uses real Chrome DevTools Protocol
