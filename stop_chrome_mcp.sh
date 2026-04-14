#!/bin/bash

# ==============================================================================
# Stop Chrome DevTools MCP Server
# ==============================================================================

set -e

COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${COLOR_BLUE}🛑 Stopping Chrome DevTools MCP Server...${NC}"

# Stop MCP server
if [ -f /tmp/chrome_mcp_server.pid ]; then
    MCP_PID=$(cat /tmp/chrome_mcp_server.pid)
    if ps -p "$MCP_PID" >/dev/null 2>&1; then
        echo -e "${COLOR_YELLOW}⚠️  Stopping MCP server (PID: $MCP_PID)...${NC}"
        kill "$MCP_PID" 2>/dev/null || true
        sleep 2
        echo -e "${COLOR_GREEN}✅ MCP server stopped${NC}"
    fi
    rm -f /tmp/chrome_mcp_server.pid
fi

# Stop Chrome debug instance
if [ -f /tmp/chrome_debug.pid ]; then
    CHROME_PID=$(cat /tmp/chrome_debug.pid)
    if ps -p "$CHROME_PID" >/dev/null 2>&1; then
        echo -e "${COLOR_YELLOW}⚠️  Stopping Chrome (PID: $CHROME_PID)...${NC}"
        kill "$CHROME_PID" 2>/dev/null || true
        sleep 2
        echo -e "${COLOR_GREEN}✅ Chrome stopped${NC}"
    fi
    rm -f /tmp/chrome_debug.pid
fi

# Also kill any remaining instances
pkill -f "Google Chrome.*remote-debugging-port" 2>/dev/null && echo -e "${COLOR_GREEN}✅ Cleaned up remaining Chrome processes${NC}" || true
pkill -f "chrome-devtools-mcp" 2>/dev/null && echo -e "${COLOR_GREEN}✅ Cleaned up remaining MCP processes${NC}" || true

echo -e "\n${COLOR_GREEN}✅ Chrome DevTools MCP Server stopped${NC}"
