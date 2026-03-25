"""AgentEazy Gateway — single FastAPI app that routes all agent requests.

Agent code is stored on a Modal Volume at /agents/{agent_name}/ with:
  - wrapper.py   (the generated FastAPI wrapper)
  - agent.json   (agent configuration)
  - repo/        (the original repo source)
  - requirements.txt
"""

import importlib.util
import inspect
import json
import logging
import os
import subprocess
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


def _validate_agent_name(agent_name: str) -> str:
    """Validate agent name to prevent path traversal attacks.

    Rejects names containing '..', '/', '\\', or null bytes.
    Returns the sanitized name or raises HTTPException.
    """
    if not agent_name or not isinstance(agent_name, str):
        raise HTTPException(status_code=400, detail="Invalid agent name")
    if ".." in agent_name or "/" in agent_name or "\\" in agent_name or "\x00" in agent_name:
        raise HTTPException(status_code=400, detail="Invalid agent name")
    # Double-check: resolved path must stay inside AGENTS_ROOT
    resolved = os.path.realpath(os.path.join(AGENTS_ROOT, agent_name))
    if not resolved.startswith(os.path.realpath(AGENTS_ROOT) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid agent name")
    return agent_name


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
_DEBUG = os.environ.get("AGENTEAZY_DEBUG", "").lower() in ("1", "true", "yes")

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
_agent_mtimes: dict[str, float] = {}  # agent_name -> mtime of agent.json when cached


def _check_stale(agent_name: str) -> None:
    """If agent files changed on disk, invalidate caches so next load picks up new code."""
    config_path = os.path.join(AGENTS_ROOT, agent_name, "agent.json")
    try:
        current_mtime = os.path.getmtime(config_path)
    except OSError:
        return
    cached_mtime = _agent_mtimes.get(agent_name)
    if cached_mtime is not None and current_mtime != cached_mtime:
        _invalidate_cache(agent_name)
        _installed_deps.discard(agent_name)

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
    _agent_mtimes[agent_name] = os.path.getmtime(config_path)
    return config


_installed_deps: set[str] = set()  # Track which agents have had deps installed


def _install_agent_deps(agent_name: str) -> None:
    """Install an agent's pip dependencies if not already installed."""
    if agent_name in _installed_deps:
        return

    agent_dir = os.path.join(AGENTS_ROOT, agent_name)
    reqs_path = os.path.join(agent_dir, "requirements.txt")

    if not os.path.isfile(reqs_path):
        _installed_deps.add(agent_name)
        return

    # Read deps, skip fastapi/uvicorn (already installed)
    skip = {"fastapi", "uvicorn"}
    deps = []
    with open(reqs_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg_name = line.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip().lower()
            if pkg_name not in skip:
                deps.append(line)

    if deps:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages"] + deps,
                capture_output=True,
                timeout=120,
            )
        except Exception:
            pass  # Best effort — some deps may fail, agent may still work

    _installed_deps.add(agent_name)


def _load_agent_func(agent_name: str):
    """Load the entry function for an agent, caching the module."""
    if agent_name in _agent_modules:
        mod = _agent_modules[agent_name]
    else:
        _install_agent_deps(agent_name)
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


def _load_agent_wrapper(agent_name: str):
    """Load an agent's wrapper.py module (which handles all import/dispatch complexity).

    The generated wrapper.py already handles relative imports, package structures,
    class-based APIs, and complex dependency chains correctly.  By delegating to
    the wrapper we avoid duplicating that logic in the gateway.

    Returns the loaded wrapper module, or None if no wrapper.py exists (legacy agents).
    """
    cache_key = f"_wrapper_{agent_name}"
    if cache_key in _agent_modules:
        return _agent_modules[cache_key]

    agent_dir = os.path.join(AGENTS_ROOT, agent_name)
    wrapper_path = os.path.join(agent_dir, "wrapper.py")

    if not os.path.isfile(wrapper_path):
        # No wrapper — caller should fall back to _load_agent_func
        return None

    # Install dependencies before loading
    _install_agent_deps(agent_name)

    # Set AGENTEAZY_REPO_PATH so the wrapper's module-level code picks up the
    # correct repo directory.  After exec_module the wrapper stores it locally,
    # so we restore the env var to avoid cross-agent contamination.
    repo_path = os.path.join(agent_dir, "repo")
    old_repo_path = os.environ.get("AGENTEAZY_REPO_PATH")
    os.environ["AGENTEAZY_REPO_PATH"] = repo_path

    try:
        spec = importlib.util.spec_from_file_location(
            f"agenteazy_wrapper_{agent_name}", wrapper_path,
            submodule_search_locations=[agent_dir],
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if old_repo_path is not None:
            os.environ["AGENTEAZY_REPO_PATH"] = old_repo_path
        else:
            os.environ.pop("AGENTEAZY_REPO_PATH", None)

    _agent_modules[cache_key] = mod
    return mod


def _invalidate_cache(agent_name: str) -> None:
    """Remove an agent from caches so it reloads on next request."""
    _agent_configs.pop(agent_name, None)
    _agent_modules.pop(agent_name, None)
    _agent_modules.pop(f"_wrapper_{agent_name}", None)


def _merge_context(func, kwargs: dict, ctx: dict) -> dict:
    """Merge shared context into kwargs, only including keys the function accepts.

    Uses inspect.signature to find accepted parameter names and **kwargs.
    """
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


def _dispatch_call(func, data: dict):
    """Dynamically map payload data to function parameters."""
    sig = inspect.signature(func)
    positional_args = []
    kwargs = {}
    extra = dict(data)

    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            # **kwargs — will receive remaining data
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            # *args — skip
            continue
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            if name in extra:
                positional_args.append(extra.pop(name))
            elif param.default is not inspect.Parameter.empty:
                positional_args.append(param.default)
            else:
                positional_args.append(None)
            continue
        if name in extra:
            kwargs[name] = extra.pop(name)
        # If not in data and has default → don't pass it (let default apply)
        elif param.default is inspect.Parameter.empty:
            # Required param not provided
            kwargs[name] = None

    # If function accepts **kwargs, pass remaining
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            kwargs.update(extra)
            break

    if positional_args:
        return func(*positional_args, **kwargs)
    return func(**kwargs)


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
    """Deduct credits from caller and pay the developer atomically. Fail-open."""
    try:
        registry_url = _get_registry_url()
        if not registry_url:
            return {}

        base = registry_url.rstrip("/")
        platform_fee = int(credits_per_call * 0.20)
        developer_credit = credits_per_call - platform_fee

        # Look up agent owner
        owner_api_key = None
        try:
            owner_req = urllib.request.Request(f"{base}/registry/agent/{agent_name}/owner")
            owner_resp = urllib.request.urlopen(owner_req, timeout=10)
            owner_data = json.loads(owner_resp.read().decode())
            owner_api_key = owner_data.get("owner_api_key")
        except Exception as e:
            _tollbooth_logger.warning("Failed to look up agent owner: %s", e)

        if owner_api_key and developer_credit > 0:
            # Atomic transfer: deduct from caller and credit developer in one call
            transfer_payload = json.dumps({
                "from_api_key": auth_token,
                "to_api_key": owner_api_key,
                "amount": developer_credit,
                "agent_name": agent_name,
            }).encode()
            transfer_req = urllib.request.Request(
                f"{base}/tollbooth/transfer", data=transfer_payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            transfer_resp = urllib.request.urlopen(transfer_req, timeout=10)
            transfer_data = json.loads(transfer_resp.read().decode())

            # Record platform fee separately (goes to platform account)
            if platform_fee > 0:
                try:
                    # Deduct the platform fee portion from caller
                    deduct_payload = json.dumps({
                        "api_key": auth_token,
                        "agent_name": agent_name,
                        "amount": platform_fee,
                    }).encode()
                    deduct_req = urllib.request.Request(
                        f"{base}/tollbooth/deduct", data=deduct_payload,
                        headers={"Content-Type": "application/json"}, method="POST",
                    )
                    urllib.request.urlopen(deduct_req, timeout=10)

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

            return {"deducted": credits_per_call, "remaining": transfer_data.get("remaining")}
        else:
            # No owner found — just deduct from caller
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
    _validate_agent_name(agent_name)
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
    _validate_agent_name(agent_name)
    await _refresh_volume()

    # TollBooth: check credits before executing
    auth = (body or {}).get("auth") or request.headers.get("x-api-key")
    toll = _check_tollbooth(agent_name, auth)
    if not toll.get("ok"):
        return JSONResponse(status_code=402, content={"error": toll["error"]})

    wrapper_mod = _load_agent_wrapper(agent_name)
    if wrapper_mod and hasattr(wrapper_mod, '_get_entry_func'):
        func = wrapper_mod._get_entry_func()
        config = _load_agent_config(agent_name)
    else:
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
    _validate_agent_name(agent_name)
    await _refresh_volume()
    # Input size check
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    # TollBooth: check credits before executing
    auth = (body or {}).get("auth") or request.headers.get("x-api-key")
    toll = _check_tollbooth(agent_name, auth)
    if not toll.get("ok"):
        return JSONResponse(status_code=402, content={"error": toll["error"]})

    payload = (body or {}).get("input", body or {})

    # Merge shared context into data before dispatch
    ctx = _agent_context.get(agent_name)
    merged_data = {**payload, **ctx} if ctx else payload

    wrapper_mod = _load_agent_wrapper(agent_name)
    if wrapper_mod and hasattr(wrapper_mod, '_get_entry_func') and hasattr(wrapper_mod, '_dispatch'):
        func = wrapper_mod._get_entry_func()
        dispatch_fn = wrapper_mod._dispatch
    else:
        func, _config = _load_agent_func(agent_name)
        dispatch_fn = _dispatch_call

    try:
        future = _executor.submit(dispatch_fn, func, merged_data)
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
        error_content = {"status": "failed", "error": str(e)}
        if _DEBUG:
            error_content["traceback"] = limited_tb
        return JSONResponse(status_code=500, content=error_content)


@app.post("/agent/{agent_name}/")
async def agent_universal(agent_name: str, request: Request, body: dict = None):
    """Universal AgentLang endpoint — route by verb."""
    _validate_agent_name(agent_name)
    try:
        await _refresh_volume()
        _check_stale(agent_name)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Content-Length header")

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
        error_content = {"status": "failed", "error": str(e)}
        if _DEBUG:
            error_content["traceback"] = limited_tb
        return JSONResponse(status_code=500, content=error_content)


def _handle_verb(agent_name: str, verb: str, payload: dict, **extra):
    """Dispatch a verb to the appropriate handler."""

    if verb == "ASK":
        wrapper_mod = _load_agent_wrapper(agent_name)
        if wrapper_mod and hasattr(wrapper_mod, '_get_entry_func'):
            # Use wrapper's entry func (handles classes, packages, relative imports)
            func = wrapper_mod._get_entry_func()
            config = _load_agent_config(agent_name)
        else:
            # Fallback for legacy agents without wrapper.py
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
        # Accept both {"data": {...}} and {"input": {...}} payload formats
        data = payload.get("data") or payload.get("input") or {}

        # Merge shared context into data before dispatch
        ctx = _agent_context.get(agent_name)
        merged_data = {**data, **ctx} if ctx else data

        wrapper_mod = _load_agent_wrapper(agent_name)
        if wrapper_mod and hasattr(wrapper_mod, '_get_entry_func') and hasattr(wrapper_mod, '_dispatch'):
            # Use wrapper's own dispatch (handles classes, relative imports, packages, etc.)
            func = wrapper_mod._get_entry_func()
            dispatch_fn = wrapper_mod._dispatch
        else:
            # Fallback for legacy agents without wrapper.py
            func, _config = _load_agent_func(agent_name)
            dispatch_fn = _dispatch_call

        try:
            future = _executor.submit(dispatch_fn, func, merged_data)
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
        safe_config = {
            "name": config.get("name"),
            "description": config.get("description"),
            "version": config.get("version"),
            "verbs": config.get("verbs", []),
            "entry": {
                "file": config.get("entry", {}).get("file"),
                "function": config.get("entry", {}).get("function"),
            },
        }
        log = list(_call_log.get(agent_name, []))
        return {"status": "completed", "config": safe_config, "recent_calls": log}

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

            # Look up owner of to_agent
            owner_req = urllib.request.Request(f"{base}/registry/agent/{to_agent}/owner")
            owner_resp = urllib.request.urlopen(owner_req, timeout=5)
            owner_data = json.loads(owner_resp.read().decode())
            owner_key = owner_data.get("owner_api_key")

            if not owner_key:
                return {"status": "error", "message": f"Agent {to_agent} has no registered owner to receive credits"}

            # Atomic transfer: deduct from sender and credit recipient in one call
            transfer_payload = json.dumps({
                "from_api_key": auth_token,
                "to_api_key": owner_key,
                "amount": credits,
                "agent_name": to_agent,
            }).encode()
            transfer_req = urllib.request.Request(
                f"{base}/tollbooth/transfer", data=transfer_payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            transfer_resp = urllib.request.urlopen(transfer_req, timeout=10)
            transfer_data = json.loads(transfer_resp.read().decode())

            if transfer_data.get("success"):
                return {
                    "status": "completed",
                    "transferred": credits,
                    "to": to_agent,
                    "remaining_balance": transfer_data.get("remaining"),
                }
            return {"status": "error", "message": transfer_data.get("error", "Transfer failed")}
        except urllib.error.HTTPError as e:
            body = None
            try:
                body = json.loads(e.read().decode())
            except Exception:
                pass
            msg = body.get("error", str(e)) if body else str(e)
            return {"status": "error", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if verb == "TRUST":
        return {"status": "acknowledged", "message": "AgentPass not yet active"}

    if verb == "LEARN":
        return {"status": "acknowledged", "message": "Knowledge ingestion coming soon"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# deployed 20260315T221804Z
# gateway-wrapper-fix 20260316T204036Z
# final-fixes 20260317T191520Z


# ── Agent-calls-agent (internal skill dispatch) ─────────────────────────

def gateway_call(skill_name: str, data: dict) -> dict:
    """Call another skill in-process. No billing. For Layer 2 agents."""
    _install_agent_deps(skill_name)
    wrapper_mod = _load_agent_wrapper(skill_name)
    if wrapper_mod and hasattr(wrapper_mod, '_get_entry_func') and hasattr(wrapper_mod, '_dispatch'):
        func = wrapper_mod._get_entry_func()
        return wrapper_mod._dispatch(func, data)
    else:
        func, _config = _load_agent_func(skill_name)
        return _dispatch_call(func, data)


# Expose call_skill to agent code as an importable module
import types as _types
_runtime_mod = _types.ModuleType("agenteazy_runtime")
_runtime_mod.call_skill = gateway_call
_runtime_mod.__doc__ = "AgentEazy runtime helpers — available to all skills running on the gateway."
sys.modules["agenteazy_runtime"] = _runtime_mod
