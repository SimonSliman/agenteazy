"""Wrapper template generator - Creates a FastAPI server from agent config."""

import ast
import json
import os


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

    # Compute module name from file path
    entry_module = entry_file.replace(".py", "").replace("/", ".").replace(os.sep, ".")

    # Use repr() for safe embedding of the config JSON string
    config_json_repr = repr(json.dumps(agent_config))

    # Build the argument unpacking for the entry function call
    if entry_args:
        call_args = ", ".join(f'{a}=payload.get("{a}")' for a in entry_args)
    else:
        call_args = ""

    code = f'''"""Auto-generated FastAPI wrapper for {name}."""

import json
import sys
import os
import importlib.util

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn


# --- Agent config ---
AGENT_CONFIG = json.loads({config_json_repr})


# --- Load the wrapped module ---
REPO_PATH = os.environ.get("AGENTEAZY_REPO_PATH", os.path.join(os.path.dirname(__file__), "repo"))
sys.path.insert(0, REPO_PATH)

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
            spec = importlib.util.spec_from_file_location(
                ENTRY_MODULE,
                os.path.join(REPO_PATH, "{entry_file}"),
            )
            _module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_module)
    return _module


def _get_entry_func():
    mod = _load_module()
    func = getattr(mod, ENTRY_FUNCTION, None)
    if func is None:
        raise HTTPException(status_code=500, detail=f"Function {{ENTRY_FUNCTION}} not found in {{ENTRY_MODULE}}")
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


@app.post("/do")
def do(body: dict = None):
    """Execute the entry function with the provided input."""
    payload = (body or {{}}).get("input", body or {{}})
    func = _get_entry_func()
    try:
        result = func({call_args})
        return {{"status": "completed", "output": result}}
    except Exception as e:
        return {{"status": "error", "error": str(e)}}


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
