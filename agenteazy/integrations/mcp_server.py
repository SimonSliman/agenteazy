"""
AgentEazy MCP Server

Exposes the AgentEazy registry as MCP tools. Every registered agent becomes
a callable tool in any MCP-compatible client (Claude Desktop, Cursor, etc.).

Usage:
    agenteazy mcp-server                    # Start with defaults
    agenteazy mcp-server --registry URL     # Custom registry
    agenteazy mcp-server --gateway URL      # Custom gateway

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
        "mcpServers": {
            "agenteazy": {
                "command": "agenteazy",
                "args": ["mcp-server"]
            }
        }
    }
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _fetch_json(url: str, timeout: int = 10) -> Any:
    """Fetch JSON from a URL using stdlib only."""
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def _post_json(url: str, data: dict, timeout: int = 30) -> Any:
    """POST JSON to a URL using stdlib only."""
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def create_mcp_server(
    registry_url: str = None,
    gateway_url: str = None,
    api_key: str = None,
):
    """
    Create an MCP server that exposes AgentEazy agents as tools.

    The server provides:
    1. A "search_agents" tool to discover agents by query
    2. A "list_agents" tool to list all available agents
    3. A "call_agent" tool to call any agent with DO verb
    4. Individual tools for each registered agent (auto-discovered)

    Returns an MCP Server instance ready to run.
    """
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
    except ImportError:
        raise ImportError(
            "MCP SDK not installed. Install with: pip install agenteazy[mcp]"
        )

    from agenteazy.config import (
        DEFAULT_REGISTRY_URL, DEFAULT_GATEWAY_URL,
        get_api_key, get_registry_url, get_gateway_url,
    )

    _registry = registry_url or get_registry_url() or DEFAULT_REGISTRY_URL
    _gateway = gateway_url or get_gateway_url() or DEFAULT_GATEWAY_URL
    _api_key = api_key or get_api_key()

    server = Server("agenteazy")

    # Cache agent list to avoid hitting registry on every tool_list call
    _agent_cache: dict = {"agents": [], "last_fetched": 0}

    def _get_agents() -> list[dict]:
        """Fetch agent list from registry, with simple caching."""
        import time
        now = time.time()
        if now - _agent_cache["last_fetched"] < 60:  # Cache for 60s
            return _agent_cache["agents"]
        try:
            agents = _fetch_json(f"{_registry.rstrip('/')}/registry/all")
            if isinstance(agents, list):
                _agent_cache["agents"] = agents
                _agent_cache["last_fetched"] = now
        except Exception as e:
            logger.warning(f"Failed to fetch agents: {e}")
        return _agent_cache["agents"]

    def _call_agent(agent_name: str, data: dict) -> dict:
        """Call an agent via the gateway."""
        url = f"{_gateway.rstrip('/')}/agent/{agent_name}/"
        payload = {"verb": "DO", "payload": {"data": data}}
        if _api_key:
            payload["auth"] = _api_key
        return _post_json(url, payload)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return available tools: core tools + one per agent."""
        tools = []

        # Core tool: search the registry
        tools.append(Tool(
            name="agenteazy_search",
            description="Search the AgentEazy agent registry. Returns agents matching your query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'password strength', 'date parsing', 'text validation')",
                    },
                },
                "required": ["query"],
            },
        ))

        # Core tool: list all agents
        tools.append(Tool(
            name="agenteazy_list",
            description="List all available agents in the AgentEazy registry.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ))

        # Core tool: call any agent by name
        tools.append(Tool(
            name="agenteazy_call",
            description="Call any AgentEazy agent by name. Pass the agent name and a JSON data object.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "Agent name (e.g., 'zxcvbn-python', 'langdetect', 'autopep8')",
                    },
                    "data": {
                        "type": "object",
                        "description": "Input data to pass to the agent",
                        "additionalProperties": True,
                    },
                },
                "required": ["agent", "data"],
            },
        ))

        # Per-agent tools (auto-discovered from registry)
        agents = _get_agents()
        for agent in agents:
            name = agent.get("name", "")
            desc = agent.get("description", "")
            if not name:
                continue

            # Sanitize name for MCP tool naming (alphanumeric + underscore only)
            tool_name = f"agent_{name.replace('-', '_')}"

            tools.append(Tool(
                name=tool_name,
                description=f"AgentEazy agent: {desc[:200]}" if desc else f"Call the {name} agent",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "object",
                            "description": f"Input data for the {name} agent",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["data"],
                },
            ))

        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle tool calls."""

        # Core: search
        if name == "agenteazy_search":
            query = arguments.get("query", "")
            try:
                results = _fetch_json(
                    f"{_registry.rstrip('/')}/registry/search?q={urllib.parse.quote(query)}"
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(results, indent=2),
                )]
            except Exception as e:
                return [TextContent(type="text", text=f"Search error: {e}")]

        # Core: list
        if name == "agenteazy_list":
            agents = _get_agents()
            summary = [{"name": a.get("name"), "description": a.get("description", "")[:100]} for a in agents]
            return [TextContent(
                type="text",
                text=json.dumps(summary, indent=2),
            )]

        # Core: call by name
        if name == "agenteazy_call":
            agent_name = arguments.get("agent", "")
            data = arguments.get("data", {})
            try:
                result = _call_agent(agent_name, data)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )]
            except Exception as e:
                return [TextContent(type="text", text=f"Agent call error: {e}")]

        # Per-agent tool: agent_{name}
        if name.startswith("agent_"):
            agent_name = name[6:].replace("_", "-")
            data = arguments.get("data", {})
            try:
                result = _call_agent(agent_name, data)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )]
            except Exception as e:
                return [TextContent(type="text", text=f"Agent call error: {e}")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def run_server(
    registry_url: str = None,
    gateway_url: str = None,
    api_key: str = None,
):
    """Run the MCP server over stdio."""
    try:
        from mcp.server.stdio import stdio_server
    except ImportError:
        raise ImportError(
            "MCP SDK not installed. Install with: pip install agenteazy[mcp]"
        )

    server = create_mcp_server(
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)
