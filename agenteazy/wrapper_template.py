"""Wrapper template generator - Creates a FastAPI server from agent config."""

import ast
import inspect
import json
import os

from agenteazy.agentlang import VALID_VERBS as _CANONICAL_VERBS


def generate_wrapper(agent_config: dict, repo_path: str) -> str:
    """
    Generate a complete, runnable FastAPI wrapper as a Python source string.

    Endpoints:
      GET  /                      - Agent info
      GET  /health                - Health check
      POST /ask                   - Describe capabilities
      POST /do                    - Execute the entry function
      GET  /.well-known/agent.json - Serve agent.json
    """
    name = agent_config["name"]
    entry_file = agent_config["entry"]["file"]
    entry_function = agent_config["entry"]["function"]
    entry_args = agent_config["entry"]["args"]
    entry_class_name = agent_config["entry"].get("class_name")
    python_root = agent_config.get("python_root", ".")

    if not entry_file or not entry_function:
        raise ValueError(
            "Cannot generate wrapper: agent.json has no entry point configured. "
            "Edit agent.json to set entry.file and entry.function."
        )

    # Compute module name from file path, stripping python_root prefix
    module_path = entry_file
    if python_root != "." and module_path.startswith(python_root + "/"):
        module_path = module_path[len(python_root) + 1:]
    entry_module = module_path.replace(".py", "").replace("/", ".").replace(os.sep, ".")

    # Use repr() for safe embedding of the config JSON string
    config_json_repr = repr(json.dumps(agent_config))

    code = f'''"""Auto-generated FastAPI wrapper for {name}."""

import inspect
import json
import sys
import os
import signal
import traceback
import importlib.util
import urllib.request
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

MAX_REQUEST_BODY_BYTES = 1_048_576  # 1 MB
FUNCTION_TIMEOUT_SECONDS = 25
_DEBUG = os.environ.get("AGENTEAZY_DEBUG", "").lower() in ("1", "true", "yes")
_executor = ThreadPoolExecutor(max_workers=4)

# --- AgentLang protocol ---
VALID_VERBS = {_CANONICAL_VERBS}
_call_log = deque(maxlen=50)
_agent_context = {{}}


def _log_call(verb, status):
    _call_log.append({{"verb": verb, "timestamp": datetime.now(timezone.utc).isoformat(), "status": status}})


def _dispatch(func, payload):
    """Dynamically map payload keys to function parameters."""
    sig = inspect.signature(func)
    kwargs = {{}}
    extra = dict(payload)  # copy so we can pop consumed keys

    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            # **kwargs — will receive all remaining payload
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            # *args — skip, we use keyword dispatch
            continue
        if name in extra:
            kwargs[name] = extra.pop(name)
        elif param.default is inspect.Parameter.empty:
            # Required param not in payload — include as None with warning
            kwargs[name] = None

    # If function accepts **kwargs, pass remaining payload
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            kwargs.update(extra)
            break

    return func(**kwargs)


# --- Agent config ---
AGENT_CONFIG = json.loads({config_json_repr})


# --- Load the wrapped module ---
REPO_PATH = os.environ.get("AGENTEAZY_REPO_PATH", os.path.join(os.path.dirname(__file__), "repo"))
PYTHON_ROOT = os.path.join(REPO_PATH, "{python_root}")
sys.path.insert(0, PYTHON_ROOT)

ENTRY_MODULE = "{entry_module}"
ENTRY_FUNCTION = "{entry_function}"

_module = None


def _load_module():
    global _module
    if _module is None:
        try:
            _module = importlib.import_module(ENTRY_MODULE)
        except ImportError:
            # Try loading by file path
            file_path = os.path.join(REPO_PATH, "{entry_file}")
            if not os.path.isfile(file_path):
                raise HTTPException(
                    status_code=500,
                    detail=f"Entry file not found: {{file_path}}. Check agent.json entry.file."
                )
            spec = importlib.util.spec_from_file_location(ENTRY_MODULE, file_path)
            _module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(_module)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load module {{ENTRY_MODULE}}: {{type(e).__name__}}: {{e}}"
                )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to import {{ENTRY_MODULE}}: {{type(e).__name__}}: {{e}}"
            )
    return _module


ENTRY_CLASS = {repr(entry_class_name)}

_instance = None


def _get_entry_func():
    global _instance
    mod = _load_module()
    if ENTRY_CLASS:
        cls = getattr(mod, ENTRY_CLASS, None)
        if cls is None:
            raise HTTPException(
                status_code=500,
                detail=f"Class '{{ENTRY_CLASS}}' not found in {{ENTRY_MODULE}}."
            )
        if _instance is None:
            _instance = cls()
        func = getattr(_instance, ENTRY_FUNCTION, None)
        if func is None:
            raise HTTPException(
                status_code=500,
                detail=f"Method '{{ENTRY_FUNCTION}}' not found on class '{{ENTRY_CLASS}}'."
            )
        return func
    func = getattr(mod, ENTRY_FUNCTION, None)
    if func is None:
        available = [n for n in dir(mod) if not n.startswith("_") and callable(getattr(mod, n, None))]
        raise HTTPException(
            status_code=500,
            detail=f"Function '{{ENTRY_FUNCTION}}' not found in {{ENTRY_MODULE}}. "
                   f"Available functions: {{', '.join(available) or 'none'}}"
        )
    return func


# --- FastAPI app ---
app = FastAPI(title=AGENT_CONFIG["name"], description=AGENT_CONFIG["description"])


@app.get("/")
def agent_info():
    """Return basic agent information."""
    return {{
        "name": AGENT_CONFIG["name"],
        "description": AGENT_CONFIG["description"],
        "version": AGENT_CONFIG["version"],
        "status": "active",
        "verbs": AGENT_CONFIG["verbs"],
    }}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {{"healthy": True, "status": "ok"}}


@app.post("/ask")
def ask(body: dict = None):
    """Describe what this agent can do."""
    try:
        func = _get_entry_func()
        docstring = func.__doc__
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load agent: {{type(e).__name__}}: {{e}}")
    return {{
        "name": AGENT_CONFIG["name"],
        "description": AGENT_CONFIG["description"],
        "verbs": AGENT_CONFIG["verbs"],
        "entry": AGENT_CONFIG["entry"],
        "capabilities": {{
            "args": AGENT_CONFIG["entry"]["args"],
            "docstring": docstring,
        }},
    }}


@app.post("/do")
async def do(request: Request, body: dict = None):
    """Execute the entry function with the provided input."""
    # Input size check: reject bodies > 1 MB
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    payload = (body or {{}}).get("input", body or {{}})
    try:
        func = _get_entry_func()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load agent: {{type(e).__name__}}: {{e}}")

    try:
        future = _executor.submit(_dispatch, func, payload)
        result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
        return {{"status": "completed", "output": result}}
    except FuturesTimeoutError:
        future.cancel()
        return JSONResponse(
            status_code=504,
            content={{
                "status": "timeout",
                "error": f"Function timed out after {{FUNCTION_TIMEOUT_SECONDS}} seconds",
            }},
        )
    except Exception as e:
        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
        limited_tb = "".join(tb_lines[-5:])
        error_content = {{"status": "failed", "error": str(e)}}
        if _DEBUG:
            error_content["traceback"] = limited_tb
        return JSONResponse(status_code=500, content=error_content)


@app.post("/")
async def universal(request: Request, body: dict = None):
    """Universal AgentLang endpoint — route by verb."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    body = body or {{}}
    verb = body.get("verb", "").upper()
    payload = body.get("payload", {{}})

    if verb not in VALID_VERBS:
        return JSONResponse(status_code=400, content={{"error": "Unknown verb", "valid_verbs": VALID_VERBS}})

    try:
        result = _handle_verb(verb, payload)
        _log_call(verb, "success")
        return result
    except HTTPException:
        _log_call(verb, "failed")
        raise
    except Exception as e:
        _log_call(verb, "failed")
        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
        limited_tb = "".join(tb_lines[-5:])
        error_content = {{"status": "failed", "error": str(e)}}
        if _DEBUG:
            error_content["traceback"] = limited_tb
        return JSONResponse(status_code=500, content=error_content)


def _handle_verb(verb, payload):
    if verb == "ASK":
        func = _get_entry_func()
        return {{
            "name": AGENT_CONFIG["name"],
            "description": AGENT_CONFIG["description"],
            "verbs": AGENT_CONFIG["verbs"],
            "entry": AGENT_CONFIG["entry"],
            "capabilities": {{
                "args": AGENT_CONFIG["entry"]["args"],
                "docstring": func.__doc__,
            }},
        }}

    if verb == "DO":
        func = _get_entry_func()
        data = payload.get("data", {{}})
        # Inject shared context if function accepts **kwargs
        if _agent_context:
            sig = inspect.signature(func)
            for p in sig.parameters.values():
                if p.kind == inspect.Parameter.VAR_KEYWORD:
                    data["_context"] = _agent_context
                    break
        try:
            future = _executor.submit(_dispatch, func, data)
            result = future.result(timeout=FUNCTION_TIMEOUT_SECONDS)
            return {{"status": "completed", "output": result}}
        except FuturesTimeoutError:
            future.cancel()
            return JSONResponse(status_code=504, content={{"status": "timeout", "error": f"Function timed out after {{FUNCTION_TIMEOUT_SECONDS}} seconds"}})

    if verb == "FIND":
        registry_url = os.environ.get("AGENTEAZY_REGISTRY_URL", "")
        if not registry_url:
            return {{"status": "failed", "error": "No registry URL configured"}}
        query = payload.get("data", "")
        search_url = f"{{registry_url.rstrip('/')}}/registry/search?q={{urllib.parse.quote(str(query))}}"
        try:
            req = urllib.request.Request(search_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                results = json.loads(resp.read().decode())
            return {{"status": "completed", "results": results}}
        except Exception as e:
            return {{"status": "failed", "error": f"Registry search failed: {{e}}"}}

    if verb == "REPORT":
        safe_config = {{
            "name": AGENT_CONFIG.get("name"),
            "description": AGENT_CONFIG.get("description"),
            "version": AGENT_CONFIG.get("version"),
            "verbs": AGENT_CONFIG.get("verbs", []),
        }}
        return {{"status": "completed", "config": safe_config, "recent_calls": list(_call_log)}}

    if verb == "SHARE":
        data = payload.get("data", {{}})
        _agent_context.update(data)
        return {{"status": "received", "context_keys": list(_agent_context.keys())}}

    if verb == "STOP":
        return {{"status": "acknowledged", "message": "No running tasks to stop"}}

    if verb == "WATCH":
        return {{"status": "acknowledged", "subscription_id": str(uuid4()), "message": "Webhooks coming soon"}}

    if verb == "PAY":
        return {{"status": "acknowledged", "message": "TollBooth not yet active"}}

    if verb == "TRUST":
        return {{"status": "acknowledged", "message": "AgentPass not yet active"}}

    if verb == "LEARN":
        return {{"status": "acknowledged", "message": "Knowledge ingestion coming soon"}}


@app.get("/.well-known/agent.json")
def well_known_agent_json():
    """Serve the agent.json configuration."""
    return JSONResponse(content=AGENT_CONFIG)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
    return code


def validate_wrapper(code: str) -> bool:
    """Validate that the generated wrapper is syntactically valid Python."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False
