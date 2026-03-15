"""LangChain integration — use AgentEazy agents as LangChain tools."""

try:
    from langchain_core.tools import BaseTool
except ImportError:
    raise ImportError(
        "LangChain integration requires langchain-core. "
        "Install it with: pip install langchain-core"
    )

import json
from typing import Any

from pydantic import Field

from agenteazy.sdk import AgentEazy, AgentEazyError


class AgentEazyTool(BaseTool):
    """A LangChain tool that calls an AgentEazy agent."""

    name: str = ""
    description: str = ""
    agent_name: str = ""
    client: Any = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_agent(
        cls,
        agent_name: str,
        registry_url: str = "https://simondusable--agenteazy-registry-serve.modal.run",
        gateway_url: str = "https://simondusable--agenteazy-gateway-serve.modal.run",
        api_key: str | None = None,
        description_override: str | None = None,
    ) -> "AgentEazyTool":
        """
        Create a LangChain tool from an AgentEazy agent.

        Fetches the agent's info from the registry to populate
        the tool name and description automatically.
        """
        client = AgentEazy(
            registry_url=registry_url,
            gateway_url=gateway_url,
            api_key=api_key,
        )

        # Fetch agent info for name/description
        try:
            info = client.agent_info(agent_name)
            desc = description_override or info.get(
                "description", f"Call the {agent_name} agent"
            )
            entry_func = info.get("entry_function", "")
            tags = info.get("tags", [])
            if not description_override:
                if entry_func:
                    desc += f" (function: {entry_func})"
                if tags:
                    desc += f" [tags: {', '.join(tags)}]"
        except AgentEazyError:
            desc = description_override or f"Call the {agent_name} agent via AgentEazy"

        # LangChain tool names must be valid identifiers (no hyphens)
        tool_name = agent_name.replace("-", "_")

        return cls(
            name=tool_name,
            description=desc,
            agent_name=agent_name,
            client=client,
        )

    def _run(self, *args: Any, **kwargs: Any) -> str:
        """Call the agent with the provided arguments."""
        # Handle single string input from some LangChain agent executors
        if args and isinstance(args[0], str):
            data = {"input": args[0]}
        elif "__arg1" in kwargs:
            data = {"input": kwargs.pop("__arg1")}
        elif kwargs:
            data = kwargs
        else:
            data = {}

        try:
            result = self.client.do(self.agent_name, data)
            output = result.get("output", result)
            if isinstance(output, dict):
                return json.dumps(output)
            return str(output)
        except AgentEazyError as e:
            return f"Agent error: {e}"

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Async version — falls back to sync for now."""
        return self._run(*args, **kwargs)


class AgentEazyToolkit:
    """Creates multiple LangChain tools from AgentEazy registry queries."""

    def __init__(
        self,
        registry_url: str = "https://simondusable--agenteazy-registry-serve.modal.run",
        gateway_url: str = "https://simondusable--agenteazy-gateway-serve.modal.run",
        api_key: str | None = None,
    ):
        self.registry_url = registry_url
        self.gateway_url = gateway_url
        self.api_key = api_key

    def get_tools(
        self,
        query: str | None = None,
        agent_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[AgentEazyTool]:
        """
        Get a list of LangChain tools.

        Either search by query or provide specific agent names.

        Args:
            query: Search the registry (e.g., "text processing")
            agent_names: Specific agent names to load
            limit: Max tools to return from search
        """
        if agent_names:
            return [
                AgentEazyTool.from_agent(
                    name,
                    registry_url=self.registry_url,
                    gateway_url=self.gateway_url,
                    api_key=self.api_key,
                )
                for name in agent_names
            ]

        client = AgentEazy(
            registry_url=self.registry_url,
            gateway_url=self.gateway_url,
            api_key=self.api_key,
        )

        if query:
            agents = client.find(query, limit=limit)
        else:
            agents = client.list_agents()[:limit]

        return [
            AgentEazyTool.from_agent(
                a["name"],
                registry_url=self.registry_url,
                gateway_url=self.gateway_url,
                api_key=self.api_key,
            )
            for a in agents
            if a.get("name")
        ]
