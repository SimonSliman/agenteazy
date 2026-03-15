"""CrewAI integration — use AgentEazy agents as CrewAI tools."""

try:
    from crewai.tools import BaseTool as CrewBaseTool
except ImportError:
    try:
        from crewai_tools import BaseTool as CrewBaseTool
    except ImportError:
        raise ImportError(
            "CrewAI integration requires crewai. "
            "Install it with: pip install crewai"
        )

import json
from typing import Any

from pydantic import Field

from agenteazy.sdk import AgentEazy, AgentEazyError


class AgentEazyCrewTool(CrewBaseTool):
    """A CrewAI tool that calls an AgentEazy agent."""

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
    ) -> "AgentEazyCrewTool":
        """Create a CrewAI tool from an AgentEazy agent."""
        client = AgentEazy(
            registry_url=registry_url,
            gateway_url=gateway_url,
            api_key=api_key,
        )

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

        tool_name = agent_name.replace("-", "_")

        return cls(
            name=tool_name,
            description=desc,
            agent_name=agent_name,
            client=client,
        )

    def _run(self, *args: Any, **kwargs) -> str:
        """Call the agent. CrewAI may pass a single string or kwargs."""
        # Handle single string argument (some CrewAI versions pass this way)
        argument = ""
        if args and isinstance(args[0], str):
            argument = args[0]

        if argument and not kwargs:
            try:
                parsed = json.loads(argument)
                if isinstance(parsed, dict):
                    kwargs = parsed
                else:
                    kwargs = {"input": argument}
            except (ValueError, TypeError):
                kwargs = {"input": argument}

        try:
            result = self.client.do(self.agent_name, kwargs)
            output = result.get("output", result)
            if isinstance(output, dict):
                return json.dumps(output)
            return str(output)
        except AgentEazyError as e:
            return f"Agent error: {e}"
