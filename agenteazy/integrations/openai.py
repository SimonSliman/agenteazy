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
