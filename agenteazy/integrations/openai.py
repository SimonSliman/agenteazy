"""OpenAI integration for AgentEazy."""

import json
from typing import Any

from agenteazy.config import DEFAULT_GATEWAY_URL, DEFAULT_REGISTRY_URL
from agenteazy.sdk import AgentEazy


def agenteazy_tools(
    query: str | None = None,
    limit: int = 10,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    client = AgentEazy(
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )

    agents = client.find(query, limit=limit) if query else client.list_agents()[:limit]

    tools = []
    for agent in agents:
        name = agent["name"].replace("-", "_")
        description = agent.get("description", f"Call the {agent['name']} agent")

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": "Input for the agent",
                            }
                        },
                        "required": ["input"],
                    },
                },
            }
        )

    return tools
    def call_agenteazy_tool(
    tool_call: dict[str, Any],
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> dict[str, Any]:
    function = tool_call.get("function", {})
    tool_name = function.get("name")
    arguments_json = function.get("arguments", "{}")

    if not tool_name:
        raise ValueError("Missing tool/function name")

    agent_name = tool_name.replace("_", "-")

    try:
        payload = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON arguments for tool '{tool_name}': {e}") from e

    if payload is None:
        payload = {}

    if not isinstance(payload, dict):
        payload = {"input": payload}

    client = AgentEazy(
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )
    return client.do(agent_name, payload)


call_agenteazy_function = call_agenteazy_tool
