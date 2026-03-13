"""AgentEazy Gateway — single FastAPI app that routes all agent requests.

Agent code is stored on a Modal Volume at /agents/{agent_name}/ with:
  - wrapper.py   (the generated FastAPI wrapper)
  - agent.json   (agent configuration)
  - repo/        (the original repo source)
  - requirements.txt
"""

import importlib.util
import json
import os
import sys
import traceback
import urllib.request
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from uuid import uuid4

import modal
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Inlined from agenteazy.agentlang (gateway must be self-contained for Modal) ──
VERBS = {
    "ASK": {"description": "Query without changing state", "http_equiv": "GET", "requires_auth": False},
    "DO": {"description": "Execute a task, may change state", "http_equiv": "POST", "requires_auth": False},
    "FIND": {"description": "Search for agents or data", "http_equiv": "GET", "requires_auth": False},
    "PAY": {"description": "Transfer credits for service", "http_equiv": "POST", "requires_auth": True},
    "WATCH": {"description": "Subscribe to changes", "http_equiv": "POST", "requires_auth": False},
    "STOP": {"description": "Halt current task", "http_equiv": "DELETE", "requires_auth": False},
    "TRUST": {"description": "Establish authenticated session", "http_equiv": "POST", "requires_auth": False},
    "SHARE": {"description": "Pass context between agents", "http_equiv": "POST", "requires_auth": False},
    "LEARN": {"description": "Ingest new knowledge", "http_equiv": "POST", "requires_auth": True},
    "REPORT": {"description": "Get audit log of actions", "http_equiv": "GET", "requires_auth": False},
}
VALID_VERBS = list(VERBS.keys())


def validate_verb(verb: str) -> bool:
    """Check whether the given verb is one of the 10 AgentLang verbs."""
    return verb.upper() in VERBS


# ── Inlined from agenteazy.config (gateway must be self-contained for Modal) ──
def _get_registry_url() -> str | None:
    """Return the stored registry URL from ~/.agenteazy/config.json, or None."""
    import json as _json
    from pathlib import Path as _Path
    config_file = _Path.home() / ".agenteazy" / "config.json"
    if not config_file.is_file():
        return None
    try:
        with open(config_file) as f:
            return _json.load(f).get("registry_url")
    except Exception:
        return None


AGENTS_ROOT = os.environ.get("AGENTEAZY_AGENTS_ROOT", "/agents")

# Modal Volume handle – reload() before reading so newly uploaded agents are visible
_volume = modal.Volume.from_name("agenteazy-agents-vol")


def _refresh_volume() -> None:
    """Reload the Modal Volume so the container sees the latest files."""
    try:
        _volume.reload()
    except Exception:
        pass  # best-effort; avoid crashing requests if reload fails

FUNCTION_TIMEOUT_SECONDS = 25
MAX_REQUEST_BODY_BYTES = 1_048_576  # 1 MB
_executor = ThreadPoolExecutor(max_workers=8)

# Cache loaded agent modules and configs to avoid re-loading on every request
_agent_configs: dict[str, dict] = {}
_agent_modules: dict[str, object] = {}

# Call logger — last 50 calls per agent
_call_log: dict[str, deque] = {}
MAX_CALL_LOG = 50

# Per-agent shared context store
_agent_context: dict[str, dict] = {}


def _log_call(agent_name: str, verb: str, status: str) -> None:
    """Append a call record to the agent's log (max 50 entries)."""
    if agent_name not in _call_log:
        _call_log[agent_name] = deque(maxlen=MAX_CALL_LOG)
    _call_log[agent_name].append({
        "verb": verb,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
    })

app = FastAPI(title="AgentEazy Gateway", description="Single gateway routing all agent requests")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _list_agents() -> list[str]:
    """List all agent names available on the volume."""
    if not os.path.isdir(AGENTS_ROOT):
        return []
    return sorted(
        d for d in os.listdir(AGENTS_ROOT)
        if os.path.isdir(os.path.join(AGENTS_ROOT, d))
        and os.path.isfile(os.path.join(AGENTS_ROOT, d, "agent.json"))
    )


def _load_agent_config(agent_name: str) -> dict:
    """Load and cache agent.json for a given agent."""
    if agent_name in _agent_configs:
        return _agent_configs[agent_name]

    agent_dir = os.path.join(AGENTS_ROOT, agent_name)
    config_path = os.path.join(agent_dir, "agent.json")

    if not os.path.isfile(config_path):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    with open(config_path) as f:
        config = json.load(f)

    _agent_configs[agent_name] = config
    return config


def _load_agent_func(agent_name: str):
    """Load the entry function for an agent, caching the module."""
    if agent_name in _agent_modules:
        mod = _agent_modules[agent_name]
    else:
        config = _load_agent_config(agent_name)
        agent_dir = os.path.join(AGENTS_ROOT, agent_name)
        repo_path = os.path.join(agent_dir, "repo")

        entry_file = config["entry"]["file"]
        entry_module_name = entry_file.replace(".py", "").replace("/", ".")

        # Add repo to sys.path so imports resolve
        if repo_path not in sys.path:
            sys.path.insert(0, repo_path)

        # Try normal import first, fall back to file-based loading
        try:
            mod = importlib.import_module(entry_module_name)
        except ImportError:
            file_path = os.path.join(repo_path, entry_file)
            if not os.path.isfile(file_path):
                raise HTTPException(
                    status_code=500,
                    detail=f"Entry file not found: {entry_file} for agent '{agent_name}'"
                )
            spec = importlib.util.spec_from_file_location(
                f"agenteazy_agent_{agent_name}", file_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

        _agent_modules[agent_name] = mod

    config = _load_agent_config(agent_name)
    func_name = config["entry"]["function"]
    func = getattr(mod, func_name, None)
    if func is None:
        raise HTTPException(
            status_code=500,
            detail=f"Function '{func_name}' not found in agent '{agent_name}'"
        )
    return func, config


def _invalidate_cache(agent_name: str) -> None:
    """Remove an agent from caches so it reloads on next request."""
    _agent_configs.pop(agent_name, None)
    _agent_modules.pop(agent_name, None)


# ── Endpoints ──────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Gateway health check."""
    return {"healthy": True, "status": "ok", "service": "agenteazy-gateway"}


@app.get("/agents")
def list_all_agents():
    """List all available agents on the volume."""
    _refresh_volume()
    agent_names = _list_agents()
    agents = []
    for name in agent_names:
        try:
            config = _load_agent_config(name)
            agents.append({
                "name": config.get("name", name),
                "description": config.get("description", ""),
                "version": config.get("version", "unknown"),
                "verbs": config.get("verbs", []),
            })
        except Exception:
            agents.append({"name": name, "description": "error loading config", "version": "unknown", "verbs": []})
    return {"agents": agents, "count": len(agents)}


@app.get("/agent/{agent_name}")
def agent_info(agent_name: str):
    """Return basic info about a specific agent."""
    _refresh_volume()
    config = _load_agent_config(agent_name)
    return {
        "name": config.get("name", agent_name),
        "description": config.get("description", ""),
        "version": config.get("version", "unknown"),
        "status": "active",
        "verbs": config.get("verbs", []),
        "entry": config.get("entry", {}),
    }


@app.post("/agent/{agent_name}/ask")
def agent_ask(agent_name: str):
    """Return an agent's capabilities."""
    _refresh_volume()
    func, config = _load_agent_func(agent_name)
    return {
        "name": config.get("name", agent_name),
        "description": config.get("description", ""),
        "verbs": config.get("verbs", []),
        "entry": config.get("entry", {}),
        "capabilities": {
            "args": config["entry"]["args"],
            "docstring": func.__doc__,
        },
    }


@app.post("/agent/{agent_name}/do")
async def agent_do(agent_name: str, request: Request, body: dict = None):
    """Execute an agent's entry function."""
    _refresh_volume()
    # Input size check
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")

    func, config = _load_agent_func(agent_name)
    entry_args = config["entry"]["args"]
    payload = (body or {}).get("input", body or {})

    # Build kwargs from the entry args
    kwargs = {a: payload.get(a) for a in entry_args} if entry_args else {}

    # Inject shared context if function accepts **kwargs
    ctx = _agent_context.get(agent_name)
    if ctx:
        import inspect
        sig = inspect.signature(func)
        for p in sig.parameters.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                kwargs["_context"] = ctx
                break

    try:
        if kwargs:
            future = _executor.submit(func, **kwargs)
        else:
            future = _executor.submit(func)
        result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
        return {"status": "completed", "output": result}
    except FuturesTimeoutError:
        future.cancel()
        return JSONResponse(
            status_code=504,
            content={
                "status": "timeout",
                "error": f"Function timed out after {FUNCTION_TIMEOUT_SECONDS} seconds",
            },
        )
    except Exception as e:
        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
        limited_tb = "".join(tb_lines[-5:])
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "error": str(e),
                "traceback": limited_tb,
            },
        )


@app.post("/agent/{agent_name}/")
async def agent_universal(agent_name: str, request: Request, body: dict = None):
    """Universal AgentLang endpoint — route by verb."""
    _refresh_volume()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")

    body = body or {}
    verb = body.get("verb", "").upper()
    payload = body.get("payload", {})

    if not validate_verb(verb):
        return JSONResponse(
            status_code=400,
            content={"error": "Unknown verb", "valid_verbs": VALID_VERBS},
        )

    try:
        result = _handle_verb(agent_name, verb, payload)
        _log_call(agent_name, verb, "success")
        return result
    except HTTPException:
        _log_call(agent_name, verb, "failed")
        raise
    except Exception as e:
        _log_call(agent_name, verb, "failed")
        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
        limited_tb = "".join(tb_lines[-5:])
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "error": str(e), "traceback": limited_tb},
        )


def _handle_verb(agent_name: str, verb: str, payload: dict):
    """Dispatch a verb to the appropriate handler."""

    if verb == "ASK":
        func, config = _load_agent_func(agent_name)
        return {
            "name": config.get("name", agent_name),
            "description": config.get("description", ""),
            "verbs": config.get("verbs", []),
            "entry": config.get("entry", {}),
            "capabilities": {
                "args": config["entry"]["args"],
                "docstring": func.__doc__,
            },
        }

    if verb == "DO":
        func, config = _load_agent_func(agent_name)
        entry_args = config["entry"]["args"]
        data = payload.get("data", {})
        task = payload.get("task")
        kwargs = {a: data.get(a) for a in entry_args} if entry_args else {}
        # Inject shared context if function accepts **kwargs
        ctx = _agent_context.get(agent_name)
        if ctx:
            import inspect
            sig = inspect.signature(func)
            for p in sig.parameters.values():
                if p.kind == inspect.Parameter.VAR_KEYWORD:
                    kwargs["_context"] = ctx
                    break

        try:
            if kwargs:
                future = _executor.submit(func, **kwargs)
            else:
                future = _executor.submit(func)
            result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
            return {"status": "completed", "output": result}
        except FuturesTimeoutError:
            future.cancel()
            return JSONResponse(
                status_code=504,
                content={
                    "status": "timeout",
                    "error": f"Function timed out after {FUNCTION_TIMEOUT_SECONDS} seconds",
                },
            )

    if verb == "FIND":
        registry_url = os.environ.get("AGENTEAZY_REGISTRY_URL") or _get_registry_url()
        if not registry_url:
            return {"status": "failed", "error": "No registry URL configured"}
        query = payload.get("data", "")
        search_url = f"{registry_url.rstrip('/')}/registry/search?q={urllib.parse.quote(str(query))}"
        try:
            req = urllib.request.Request(search_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                results = json.loads(resp.read().decode())
            return {"status": "completed", "results": results}
        except Exception as e:
            return {"status": "failed", "error": f"Registry search failed: {e}"}

    if verb == "REPORT":
        config = _load_agent_config(agent_name)
        log = list(_call_log.get(agent_name, []))
        return {"status": "completed", "config": config, "recent_calls": log}

    if verb == "SHARE":
        data = payload.get("data", {})
        if agent_name not in _agent_context:
            _agent_context[agent_name] = {}
        _agent_context[agent_name].update(data)
        return {"status": "received", "context_keys": list(_agent_context[agent_name].keys())}

    if verb == "STOP":
        return {"status": "acknowledged", "message": "No running tasks to stop"}

    if verb == "WATCH":
        return {"status": "acknowledged", "subscription_id": str(uuid4()), "message": "Webhooks coming soon"}

    if verb == "PAY":
        return {"status": "acknowledged", "message": "TollBooth not yet active"}

    if verb == "TRUST":
        return {"status": "acknowledged", "message": "AgentPass not yet active"}

    if verb == "LEARN":
        return {"status": "acknowledged", "message": "Knowledge ingestion coming soon"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
