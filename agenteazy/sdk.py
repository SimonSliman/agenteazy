"""AgentEazy SDK — find and call agents programmatically."""

import json
import urllib.error
import urllib.parse
import urllib.request

from agenteazy.config import load_config


class AgentEazyError(Exception):
    """Raised when an agent call fails."""

    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AgentEazy:
    """Client for the AgentEazy agent network."""

    def __init__(
        self,
        registry_url: str = "https://simondusable--agenteazy-registry-serve.modal.run",
        gateway_url: str = "https://simondusable--agenteazy-gateway-serve.modal.run",
        api_key: str | None = None,
    ):
        """
        Args:
            registry_url: URL of the AgentEazy registry.
            gateway_url: URL of the AgentEazy gateway.
            api_key: Your API key for calling paid agents. Optional for free agents.
        """
        self.registry_url = registry_url.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key if api_key is not None else self._load_api_key_from_config()

    def _load_api_key_from_config(self) -> str | None:
        """Load API key from ~/.agenteazy/config.json if it exists."""
        cfg = load_config()
        return cfg.get("api_key")

    def _headers(self) -> dict:
        """Build common request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, url: str, timeout: int = 10) -> dict | list:
        """Make a GET request and return parsed JSON."""
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = None
            try:
                body = json.loads(e.read().decode())
            except Exception:
                pass
            raise AgentEazyError(
                f"HTTP {e.code}: {body.get('detail', e.reason) if body else e.reason}",
                status_code=e.code,
                response=body,
            )
        except urllib.error.URLError:
            raise AgentEazyError(f"Cannot reach service at {url}")

    def _post(self, url: str, data: dict, timeout: int = 10) -> dict:
        """Make a POST request with JSON body and return parsed JSON."""
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=payload, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = None
            try:
                body = json.loads(e.read().decode())
            except Exception:
                pass
            raise AgentEazyError(
                f"HTTP {e.code}: {body.get('detail', e.reason) if body else e.reason}",
                status_code=e.code,
                response=body,
            )
        except urllib.error.URLError:
            raise AgentEazyError(f"Cannot reach service at {url}")

    def find(self, query: str, limit: int = 10) -> list[dict]:
        """
        Search the registry for agents matching a query.

        Returns a list of agent dicts with: name, description, url, verbs, tags, etc.

        Example:
            agents = client.find("password strength")
            # [{"name": "zxcvbn-python", "description": "...", ...}]
        """
        if not query or not query.strip():
            return self.list_agents()[:limit]
        encoded = urllib.parse.quote(query)
        url = f"{self.registry_url}/registry/search?q={encoded}"
        result = self._get(url)
        if isinstance(result, list):
            return result[:limit]
        return result.get("agents", result.get("results", []))[:limit]

    def call(
        self,
        agent_name: str,
        verb: str = "DO",
        data: dict | None = None,
        timeout: int = 30,
    ) -> dict:
        """
        Call an agent through the gateway using AgentLang.

        Args:
            agent_name: Name of the agent in the registry.
            verb: AgentLang verb (DO, ASK, FIND, REPORT, etc.)
            data: Payload data dict (passed as payload.data).
            timeout: Request timeout in seconds.

        Returns:
            The agent's response as a dict.

        Raises:
            AgentEazyError: On network errors, billing errors, or agent errors.

        Example:
            result = client.call("zxcvbn-python", data={"password": "test123"})
            # {"status": "completed", "output": {"score": 0, ...}}
        """
        url = f"{self.gateway_url}/agent/{agent_name}/"
        body = {"verb": verb, "payload": {"data": data or {}}}
        try:
            return self._post(url, body, timeout=timeout)
        except AgentEazyError as e:
            # Re-raise with friendlier messages for common errors
            if e.status_code == 402 or (
                e.status_code == 400
                and e.response
                and "credit" in str(e.response).lower()
            ):
                raise AgentEazyError(
                    "Not enough credits. Run: agenteazy topup",
                    status_code=e.status_code,
                    response=e.response,
                )
            if e.status_code == 404:
                raise AgentEazyError(
                    f"Agent '{agent_name}' not found in registry",
                    status_code=404,
                    response=e.response,
                )
            if e.status_code == 504:
                raise AgentEazyError(
                    f"Agent timed out after {timeout}s",
                    status_code=504,
                    response=e.response,
                )
            if e.status_code is None:
                raise AgentEazyError(
                    f"Cannot reach gateway at {self.gateway_url}",
                    response=e.response,
                )
            raise

    def ask(self, agent_name: str) -> dict:
        """Shortcut for call(agent_name, verb="ASK") — get agent capabilities."""
        return self.call(agent_name, verb="ASK")

    def do(self, agent_name: str, data: dict) -> dict:
        """Shortcut for call(agent_name, verb="DO", data=data) — execute the agent."""
        return self.call(agent_name, verb="DO", data=data)

    def list_agents(self) -> list[dict]:
        """List all agents in the registry."""
        url = f"{self.registry_url}/registry/all"
        result = self._get(url)
        if isinstance(result, list):
            return result
        return result.get("agents", [])

    def agent_info(self, agent_name: str) -> dict:
        """Get full info for a specific agent."""
        url = f"{self.registry_url}/registry/agent/{agent_name}"
        try:
            return self._get(url)
        except AgentEazyError as e:
            if e.status_code == 404:
                raise AgentEazyError(
                    f"Agent '{agent_name}' not found in registry",
                    status_code=404,
                    response=e.response,
                )
            raise
