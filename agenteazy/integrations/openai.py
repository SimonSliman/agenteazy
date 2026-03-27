"""OpenAI integration for AgentEazy.

Supports both:
- legacy OpenAI function calling: `functions=...`
- current OpenAI tool calling: `tools=...`
"""

import json
from typing import Any

from agenteazy.config import DEFAULT_GATEWAY_URL, DEFAULT_REGISTRY_URL
from agenteazy.sdk import AgentEazy


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _tool_name_from_agent_name(agent_name: str) -> str:
    return agent_name.replace("-", "_")


def _agent_name_from_tool_name(tool_name: str) -> str:
    return tool_name.replace("_", "-")


def _function_schema_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    agent_name = agent["name"]
    description = agent.get("description", f"Call the {agent_name} agent")

    return {
        "name": _tool_name_from_agent_name(agent_name),
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Natural language input for the agent.",
                }
            },
            "additionalProperties": True,
        },
    }


def _load_agents(
    query: str | None,
    limit: int,
    *,
    registry_url: str,
    gateway_url: str,
    api_key: str | None,
) -> list[dict[str, Any]]:
    client = AgentEazy(
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )
    return client.find(query, limit=limit) if query else client.list_agents()[:limit]


def agenteazy_functions(
    query: str | None = None,
    limit: int = 10,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Return legacy OpenAI function-calling schemas.

    Example:
        functions = agenteazy_functions(query="password")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[...],
            functions=functions,
        )
    """
    agents = _load_agents(
        query,
        limit,
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )
    return [_function_schema_for_agent(agent) for agent in agents if agent.get("name")]


def agenteazy_tools(
    query: str | None = None,
    limit: int = 10,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Return current OpenAI tool-calling schemas.

    Example:
        tools = agenteazy_tools(query="password")
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[...],
            tools=tools,
        )
    """
    functions = agenteazy_functions(
        query=query,
        limit=limit,
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )
    return [{"type": "function", "function": function} for function in functions]


def _extract_openai_call(function_or_tool_call: Any) -> tuple[str, str]:
    """Accept either:
    - legacy function_call: {name, arguments}
    - current tool_call: {function: {name, arguments}}
    - object versions of either shape
    """
    function = _get_attr_or_key(function_or_tool_call, "function")
    if function is not None:
        tool_name = _get_attr_or_key(function, "name")
        arguments_json = _get_attr_or_key(function, "arguments", "{}")
        if tool_name:
            return tool_name, arguments_json or "{}"

    tool_name = _get_attr_or_key(function_or_tool_call, "name")
    arguments_json = _get_attr_or_key(function_or_tool_call, "arguments", "{}")

    if not tool_name:
        raise ValueError("Missing tool/function name")

    return tool_name, arguments_json or "{}"


def call_agenteazy_function(
    function_call: Any,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Execute a legacy OpenAI function call against AgentEazy.

    Example:
        result = call_agenteazy_function(response.choices[0].message.function_call)
    """
    tool_name, arguments_json = _extract_openai_call(function_call)
    agent_name = _agent_name_from_tool_name(tool_name)

    try:
        payload = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON arguments for '{tool_name}': {e}") from e

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


def call_agenteazy_tool(
    tool_call: Any,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Execute a current OpenAI tool call against AgentEazy.

    Example:
        result = call_agenteazy_tool(response.choices[0].message.tool_calls[0])
    """
    return call_agenteazy_function(
        tool_call,
        registry_url=registry_url,
        gateway_url=gateway_url,
        api_key=api_key,
    )


__all__ = [
    "agenteazy_functions",
    "agenteazy_tools",
    "call_agenteazy_function",
    "call_agenteazy_tool",
]
