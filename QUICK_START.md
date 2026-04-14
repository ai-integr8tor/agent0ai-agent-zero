# Quick Start - Docker MCP for Agent-Zero

## Everything is Automatic! 🎉

Just use `run` and `stop` - that's it!

### Normal Version

```bash
# Start
./run_agent_zero_normal.sh

# Stop (automatic cleanup)
./stop_agent_zero.sh
```

### Hacking Version

```bash
# Start
./run_agent_zero_hacking.sh

# Stop (automatic cleanup)
./stop_agent_zero.sh
```

## What Happens Automatically

### When You Run:
1. ✅ Removes any existing MCP bridge network (from previous runs)
2. ✅ Creates fresh MCP bridge network (`agent-zero-mcp-network`)
3. ✅ Connects container to the network
4. ✅ Maps MCP port (8813 for normal, 8812 for hacking)
5. ✅ Installs Docker CLI inside container
6. ✅ Configures MCP server settings

### When You Stop:
1. ✅ Stops the container(s)
2. ✅ Disconnects containers from MCP network
3. ✅ Removes the MCP bridge network
4. ✅ Ready for next clean start!

## That's It!

No flags, no manual cleanup, no configuration needed.

Just:
```bash
./run_agent_zero_normal.sh
./stop_agent_zero.sh
```

## Optional: View Logs

```bash
docker logs -f agent-zero-normal
docker logs -f agent-zero-hacking
```

## Troubleshooting

If you see errors, try:
```bash
# Stop everything
./stop_agent_zero.sh

# Start fresh
./run_agent_zero_normal.sh
```

For detailed documentation, see [DOCKER_MCP_SETUP.md](./DOCKER_MCP_SETUP.md)
