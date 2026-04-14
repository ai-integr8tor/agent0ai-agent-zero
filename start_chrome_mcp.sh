#!/bin/bash

# ==============================================================================
# Start Chrome DevTools MCP Server
# ==============================================================================
# Starts Chrome with remote debugging and the DevTools MCP server
# ==============================================================================

set -e

COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

CHROME_DEBUG_PORT="${1:-9222}"
MCP_PORT="${2:-8816}"
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR="${HOME}/Library/Application Support/Google/Chrome-DevTools-MCP"

echo -e "${COLOR_BLUE}🚀 Starting Chrome DevTools MCP Server...${NC}"

# Check if Chrome is installed
if [ ! -f "$CHROME_PATH" ]; then
    echo -e "${COLOR_RED}❌ Chrome not found at: $CHROME_PATH${NC}"
    echo -e "${COLOR_YELLOW}💡 Please install Google Chrome${NC}"
    exit 1
fi

# Kill existing Chrome debug instances
echo -e "${COLOR_YELLOW}🔍 Checking for existing Chrome instances...${NC}"
pkill -f "Google Chrome.*remote-debugging-port=${CHROME_DEBUG_PORT}" 2>/dev/null || true
sleep 1

# Create user data directory
mkdir -p "$USER_DATA_DIR"

# Start Chrome with remote debugging
echo -e "${COLOR_BLUE}🌐 Starting Chrome with debug port ${CHROME_DEBUG_PORT}...${NC}"
"$CHROME_PATH" \
  --remote-debugging-port=${CHROME_DEBUG_PORT} \
  --user-data-dir="${USER_DATA_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-default-apps \
  --disable-extensions \
  --disable-sync \
  --disable-translate \
  --hide-scrollbars \
  --metrics-recording-only \
  --mute-audio \
  --no-first-run \
  --safebrowsing-disable-auto-update \
  --disable-features=TranslateUI \
  --disable-ipc-flooding-protection \
  >/tmp/chrome_debug.log 2>&1 &

CHROME_PID=$!
echo -e "${COLOR_GREEN}✅ Chrome started (PID: ${CHROME_PID})${NC}"

# Wait for Chrome to be ready
echo -e "${COLOR_BLUE}⏳ Waiting for Chrome to be ready...${NC}"
sleep 5

# Verify Chrome debug port is open
if lsof -i :${CHROME_DEBUG_PORT} >/dev/null 2>&1; then
    echo -e "${COLOR_GREEN}✅ Chrome debug port ${CHROME_DEBUG_PORT} is open${NC}"
else
    echo -e "${COLOR_RED}❌ Chrome debug port ${CHROME_DEBUG_PORT} is not open${NC}"
    echo -e "${COLOR_YELLOW}💡 Check logs: cat /tmp/chrome_debug.log${NC}"
    exit 1
fi

# Start Chrome DevTools MCP server
echo -e "${COLOR_BLUE}🔧 Starting Chrome DevTools MCP server on port ${MCP_PORT}...${NC}"
cd /tmp/chrome-devtools-mcp

# Create MCP server config
cat > /tmp/chrome_mcp_config.json <<EOF
{
  "port": ${MCP_PORT},
  "chrome_debug_port": ${CHROME_DEBUG_PORT},
  "chrome_host": "host.docker.internal"
}
EOF

# Start the MCP server
uv run python server.py --port ${MCP_PORT} --chrome-debug-port ${CHROME_DEBUG_PORT} >/tmp/chrome_mcp_server.log 2>&1 &
MCP_SERVER_PID=$!
echo ${MCP_SERVER_PID} > /tmp/chrome_mcp_server.pid
echo ${CHROME_PID} > /tmp/chrome_debug.pid

echo -e "${COLOR_GREEN}✅ Chrome DevTools MCP server started (PID: ${MCP_SERVER_PID})${NC}"
echo -e "${COLOR_BLUE}📋 Configuration:${NC}"
echo -e "   Chrome Debug Port: ${COLOR_YELLOW}${CHROME_DEBUG_PORT}${NC}"
echo -e "   MCP Server Port: ${COLOR_YELLOW}${MCP_PORT}${NC}"
echo -e "   User Data Dir: ${COLOR_YELLOW}${USER_DATA_DIR}${NC}"

sleep 3

# Verify MCP server is running
if lsof -i :${MCP_PORT} >/dev/null 2>&1; then
    echo -e "${COLOR_GREEN}✅ MCP server listening on port ${MCP_PORT}${NC}"
else
    echo -e "${COLOR_YELLOW}⚠️  MCP server may not have started correctly${NC}"
    echo -e "${COLOR_YELLOW}💡 Check logs: cat /tmp/chrome_mcp_server.log${NC}"
fi

echo -e "\n${COLOR_BLUE}💡 To stop:${NC}"
echo -e "   ${COLOR_YELLOW}kill ${MCP_SERVER_PID} ${CHROME_PID}${NC}"
echo -e "   ${COLOR_YELLOW}Or run: ./stop_chrome_mcp.sh${NC}"
