"""AgentEazy Gateway — single FastAPI app that routes all agent requests.

Agent code is stored on a Modal Volume at /agents/{agent_name}/ with:
  - wrapper.py   (the generated FastAPI wrapper)
  - agent.json   (agent configuration)
  - repo/        (the original repo source)
  - requirements.txt
"""

import importlib.util
import json
import logging
import os
import sys
import traceback
import urllib.request
import urllib.error
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from uuid import uuid4

import modal
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

VALID_VERBS = ["ASK", "DO", "FIND", "PAY", "WATCH", "STOP", "TRUST", "SHARE", "LEARN", "REPORT"]


def validate_verb(verb):
    return isinstance(verb, str) and verb.upper() in VALID_VERBS


def _get_registry_url():
    env_url = os.environ.get("AGENTEAZY_REGISTRY_URL")
    if env_url:
        return env_url
    import json as _json
    config_file = os.path.expanduser("~/.agenteazy/config.json")
    try:
        with open(config_file) as f:
            return _json.load(f).get("registry_url")
    except Exception:
        return None


AGENTS_ROOT = os.environ.get("AGENTEAZY_AGENTS_ROOT", "/agents")

# Modal Volume handle – reload() before reading so newly uploaded agents are visible
_volume = modal.Volume.from_name("agenteazy-agents-vol")


async def _refresh_volume() -> None:
    """Reload the Modal Volume so the container sees the latest files."""
    try:
        await _volume.reload.aio()
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


def _merge_context(func, kwargs: dict, ctx: dict) -> dict:
    """Merge shared context into kwargs, only including keys the function accepts.

    Uses inspect.signature to find accepted parameter names and **kwargs.
    """
    import inspect
    merged = dict(kwargs)
    sig = inspect.signature(func)
    param_names = set(sig.parameters.keys())
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if has_var_keyword:
        # Function accepts **kwargs — pass all context keys
        merged.update(ctx)
    else:
        # Only pass context keys that match explicit parameter names
        for key, value in ctx.items():
            if key in param_names and key not in merged:
                merged[key] = value
    return merged


# ── TollBooth helpers ──────────────────────────────────────────────────

_tollbooth_logger = logging.getLogger("agenteazy.tollbooth")


def _check_tollbooth(agent_name: str, auth_token: str | None) -> dict:
    """Check whether the caller can afford this agent. Fail-open on errors."""
    try:
        config_path = os.path.join(AGENTS_ROOT, agent_name, "agent.json")
        if not os.path.isfile(config_path):
            return {"ok": True, "free": True}

        with open(config_path) as f:
            config = json.load(f)
        pricing = config.get("pricing")
        credits_per_call = pricing.get("credits_per_call", 0) if isinstance(pricing, dict) else 0
        if not pricing or credits_per_call <= 0:
            return {"ok": True, "free": True}

        if not auth_token:
            return {
                "ok": False,
                "error": f"This agent charges {credits_per_call} credits per call. "
                         f"Get your API key: agenteazy signup <github_username>",
            }

        registry_url = _get_registry_url()
        if not registry_url:
            _tollbooth_logger.warning("No registry URL configured — letting call through")
            return {"ok": True, "free": True}

        url = f"{registry_url.rstrip('/')}/tollbooth/balance/{auth_token}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())

        balance = data.get("credits", 0)
        if balance < credits_per_call:
            return {
                "ok": False,
                "error": f"Insufficient credits. Balance: {balance}, Cost: {credits_per_call}. "
                         f"Buy more: agenteazy topup",
            }

        return {"ok": True, "free": False, "credits_per_call": credits_per_call, "balance": balance}

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "error": "Invalid API key"}
        _tollbooth_logger.error("TollBooth check failed: %s", e)
        return {"ok": True, "free": True}
    except Exception as e:
        _tollbooth_logger.error("TollBooth check failed: %s", e)
        return {"ok": True, "free": True}


def _deduct_and_pay(auth_token: str, agent_name: str, credits_per_call: int) -> dict:
    """Deduct credits from caller, pay the developer, record platform fee. Fail-open."""
    try:
        registry_url = _get_registry_url()
        if not registry_url:
            return {}

        base = registry_url.rstrip("/")
        platform_fee = int(credits_per_call * 0.20)
        developer_credit = credits_per_call - platform_fee

        # Deduct from caller
        deduct_payload = json.dumps({
            "api_key": auth_token,
            "agent_name": agent_name,
            "amount": credits_per_call,
        }).encode()
        req = urllib.request.Request(
            f"{base}/tollbooth/deduct", data=deduct_payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        deduct_result = json.loads(resp.read().decode())

        # Look up agent owner
        owner_api_key = None
        try:
            owner_req = urllib.request.Request(f"{base}/registry/agent/{agent_name}/owner")
            owner_resp = urllib.request.urlopen(owner_req, timeout=10)
            owner_data = json.loads(owner_resp.read().decode())
            owner_api_key = owner_data.get("owner_api_key")
        except Exception as e:
            _tollbooth_logger.warning("Failed to look up agent owner: %s", e)

        # Pay the developer if owner is known
        if owner_api_key and developer_credit > 0:
            try:
                earn_payload = json.dumps({
                    "api_key": owner_api_key,
                    "amount": developer_credit,
                    "source": "agent_revenue",
                }).encode()
                earn_req = urllib.request.Request(
                    f"{base}/tollbooth/earn", data=earn_payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                urllib.request.urlopen(earn_req, timeout=10)
            except Exception as e:
                _tollbooth_logger.warning("Failed to credit developer: %s", e)

        # Record platform fee
        if platform_fee > 0:
            try:
                fee_payload = json.dumps({
                    "api_key": "ae_platform",
                    "amount": platform_fee,
                    "source": "platform_fee",
                }).encode()
                fee_req = urllib.request.Request(
                    f"{base}/tollbooth/earn", data=fee_payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                urllib.request.urlopen(fee_req, timeout=10)
            except Exception as e:
                _tollbooth_logger.warning("Failed to record platform fee: %s", e)

        return {"deducted": credits_per_call, "remaining": deduct_result.get("remaining")}
    except Exception as e:
        _tollbooth_logger.error("Deduct failed: %s", e)
        return {}


# ── Endpoints ──────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Gateway health check."""
    return {"healthy": True, "status": "ok", "service": "agenteazy-gateway"}


@app.get("/agents")
async def list_all_agents():
    """List all available agents on the volume."""
    await _refresh_volume()
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
async def agent_info(agent_name: str):
    """Return basic info about a specific agent."""
    await _refresh_volume()
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
async def agent_ask(agent_name: str, request: Request, body: dict = None):
    """Return an agent's capabilities."""
    await _refresh_volume()

    # TollBooth: check credits before executing
    auth = (body or {}).get("auth") or request.headers.get("x-api-key")
    toll = _check_tollbooth(agent_name, auth)
    if not toll.get("ok"):
        return JSONResponse(status_code=402, content={"error": toll["error"]})

    func, config = _load_agent_func(agent_name)

    result = {
        "name": config.get("name", agent_name),
        "description": config.get("description", ""),
        "verbs": config.get("verbs", []),
        "entry": config.get("entry", {}),
        "capabilities": {
            "args": config["entry"]["args"],
            "docstring": func.__doc__,
        },
    }

    # Deduct after successful execution for paid agents
    if not toll.get("free"):
        _deduct_and_pay(auth, agent_name, toll["credits_per_call"])

    return result


@app.post("/agent/{agent_name}/do")
async def agent_do(agent_name: str, request: Request, body: dict = None):
    """Execute an agent's entry function."""
    await _refresh_volume()
    # Input size check
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")

    # TollBooth: check credits before executing
    auth = (body or {}).get("auth") or request.headers.get("x-api-key")
    toll = _check_tollbooth(agent_name, auth)
    if not toll.get("ok"):
        return JSONResponse(status_code=402, content={"error": toll["error"]})

    func, config = _load_agent_func(agent_name)
    entry_args = config["entry"]["args"]
    payload = (body or {}).get("input", body or {})

    # Build kwargs from the entry args
    kwargs = {a: payload.get(a) for a in entry_args} if entry_args else {}

    # Merge shared context into kwargs (only keys the function accepts)
    ctx = _agent_context.get(agent_name)
    kwargs_with_ctx = _merge_context(func, kwargs, ctx) if ctx else kwargs

    try:
        try:
            future = _executor.submit(func, **kwargs_with_ctx) if kwargs_with_ctx else _executor.submit(func)
            result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
        except TypeError:
            # Context kwargs not accepted — retry without context
            future = _executor.submit(func, **kwargs) if kwargs else _executor.submit(func)
            result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)

        # Deduct after successful execution for paid agents
        if not toll.get("free"):
            _deduct_and_pay(auth, agent_name, toll["credits_per_call"])

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
    try:
        await _refresh_volume()
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

        # TollBooth: check credits before executing
        auth = body.get("auth") or request.headers.get("x-api-key")

        # PAY is a free verb — skip billing, credits are transferred explicitly
        if verb == "PAY":
            result = _handle_verb(agent_name, verb, payload, auth=auth)
        else:
            toll = _check_tollbooth(agent_name, auth)
            if not toll.get("ok"):
                return JSONResponse(status_code=402, content={"error": toll["error"]})

            result = _handle_verb(agent_name, verb, payload)

            # Deduct after successful execution for paid agents
            if toll.get("ok") and not toll.get("free"):
                _deduct_and_pay(auth, agent_name, toll["credits_per_call"])

        _log_call(agent_name, verb, "success")
        return result
    except HTTPException:
        _log_call(agent_name, verb, "failed")
        raise
    except Exception as e:
        verb_val = body.get("verb", "") if isinstance(body, dict) else ""
        _log_call(agent_name, verb_val.upper() if verb_val else "UNKNOWN", "failed")
        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
        limited_tb = "".join(tb_lines[-5:])
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "error": str(e), "traceback": limited_tb},
        )


def _handle_verb(agent_name: str, verb: str, payload: dict, **extra):
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
        # Accept both {"data": {...}} and {"input": {...}} payload formats
        data = payload.get("data") or payload.get("input") or {}
        kwargs = {a: data.get(a) for a in entry_args} if entry_args else {}

        # Merge shared context into kwargs (only keys the function accepts)
        ctx = _agent_context.get(agent_name)
        kwargs_with_ctx = _merge_context(func, kwargs, ctx) if ctx else kwargs

        try:
            try:
                future = _executor.submit(func, **kwargs_with_ctx) if kwargs_with_ctx else _executor.submit(func)
                result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
            except TypeError:
                # Context kwargs not accepted — retry without context
                future = _executor.submit(func, **kwargs) if kwargs else _executor.submit(func)
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
        registry_url = _get_registry_url()
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
        data = payload.get("data") or payload.get("input") or {}
        if agent_name not in _agent_context:
            _agent_context[agent_name] = {}
        _agent_context[agent_name].update(data)
        return {"status": "received", "context_keys": list(_agent_context[agent_name].keys())}

    if verb == "STOP":
        return {"status": "acknowledged", "message": "No running tasks to stop"}

    if verb == "WATCH":
        return {"status": "acknowledged", "subscription_id": str(uuid4()), "message": "Webhooks coming soon"}

    if verb == "PAY":
        try:
            auth_token = extra.get("auth")
            if not auth_token:
                return {"status": "error", "message": "PAY requires authentication. Pass your API key in the auth field."}

            to_agent = payload.get("data", {}).get("to_agent") or payload.get("to_agent")
            if not to_agent:
                return {"status": "error", "message": "PAY requires to_agent in payload.data"}

            credits = payload.get("data", {}).get("credits") or payload.get("credits")
            if not credits or credits <= 0:
                return {"status": "error", "message": "PAY requires a positive credits amount in payload.data"}

            if credits > 1000:
                return {"status": "error", "message": "Maximum transfer is 1000 credits per transaction"}

            registry_url = _get_registry_url()
            if not registry_url:
                return {"status": "error", "message": "No registry URL configured"}
            base = registry_url.rstrip("/")

            # Check sender balance
            bal_req = urllib.request.Request(f"{base}/tollbooth/balance/{auth_token}")
            bal_resp = urllib.request.urlopen(bal_req, timeout=5)
            bal_data = json.loads(bal_resp.read().decode())
            balance = bal_data.get("credits", 0)
            if balance < credits:
                return {"status": "error", "message": f"Insufficient credits. Balance: {balance}"}

            # Deduct from sender
            deduct_payload = json.dumps({
                "api_key": auth_token,
                "agent_name": to_agent,
                "amount": credits,
            }).encode()
            deduct_req = urllib.request.Request(
                f"{base}/tollbooth/deduct", data=deduct_payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            deduct_resp = urllib.request.urlopen(deduct_req, timeout=5)
            deduct_data = json.loads(deduct_resp.read().decode())
            remaining = deduct_data.get("remaining", balance - credits)

            # Look up owner of to_agent
            owner_req = urllib.request.Request(f"{base}/registry/agent/{to_agent}/owner")
            owner_resp = urllib.request.urlopen(owner_req, timeout=5)
            owner_data = json.loads(owner_resp.read().decode())
            owner_key = owner_data.get("owner_api_key")

            if not owner_key:
                return {"status": "error", "message": f"Agent {to_agent} has no registered owner to receive credits"}

            # Credit the recipient
            earn_payload = json.dumps({
                "api_key": owner_key,
                "amount": credits,
                "source": "pay_transfer",
            }).encode()
            earn_req = urllib.request.Request(
                f"{base}/tollbooth/earn", data=earn_payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(earn_req, timeout=5)

            return {"status": "completed", "transferred": credits, "to": to_agent, "remaining_balance": remaining}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if verb == "TRUST":
        return {"status": "acknowledged", "message": "AgentPass not yet active"}

    if verb == "LEARN":
        return {"status": "acknowledged", "message": "Knowledge ingestion coming soon"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
