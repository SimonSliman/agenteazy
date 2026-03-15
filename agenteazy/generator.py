"""Agent JSON generator - Creates agent.json from repo analysis."""

import json
import os
from datetime import datetime, timezone


def _bump_patch_version(version: str) -> str:
    """Bump the patch component of a semver string: 0.1.0 -> 0.1.1."""
    parts = version.split(".")
    if len(parts) != 3:
        return "0.1.1"
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        parts[2] = "1"
    return ".".join(parts)


def _get_existing_version(output_dir: str) -> str | None:
    """Read version from an existing agent.json in the output directory."""
    agent_path = os.path.join(output_dir, "agent.json")
    if not os.path.isfile(agent_path):
        return None
    try:
        with open(agent_path) as f:
            existing = json.load(f)
        return existing.get("version")
    except (json.JSONDecodeError, OSError):
        return None


def generate_agent_json(analysis, output_dir: str | None = None) -> dict:
    """
    Generate an agent.json configuration from a RepoAnalysis object.

    If output_dir is provided and contains an existing agent.json,
    the patch version is auto-incremented.

    Returns a dict suitable for serialization to agent.json.
    """
    entry = analysis.suggested_entry

    # Try to get a description from the entry point's docstring
    description = None
    if entry and entry.docstring:
        description = entry.docstring.split("\n")[0].strip()
    if not description:
        description = f"AI agent wrapping {analysis.repo_name}"

    # Determine version: bump if existing, else start at 0.1.0
    version = "0.1.0"
    if output_dir:
        existing_version = _get_existing_version(output_dir)
        if existing_version:
            version = _bump_patch_version(existing_version)

    config = {
        "name": analysis.repo_name,
        "description": description,
        "version": version,
        "language": analysis.language,
        "entry": {
            "file": entry.file if entry else None,
            "function": entry.name if entry else None,
            "class_name": entry.class_name if entry else None,
            "args": entry.args if entry else [],
            "posonly_args": entry.posonly_args if entry and entry.posonly_args else [],
        },
        "dependencies": {
            "file": "requirements.txt" if analysis.has_requirements_txt else None,
        },
        "verbs": ["ASK", "DO"],
    }

    if entry is None:
        config["_note"] = "No entry point detected. Edit entry.file and entry.function manually."

    return config


def add_pricing(config: dict, credits_per_call: int) -> dict:
    """Add pricing configuration to an agent config dict."""
    config["pricing"] = {"model": "per_call", "credits_per_call": credits_per_call}
    return config


def save_agent_json(config: dict, output_dir: str) -> str:
    """
    Write agent.json to the output directory.

    Returns the path to the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "agent.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    return path


def load_agent_json(path: str) -> dict:
    """Read an existing agent.json file and return its contents."""
    with open(path) as f:
        return json.load(f)


def _get_history_path() -> str:
    """Return the path to .agenteazy/deploy-history.json, creating the dir if needed."""
    history_dir = os.path.join(os.path.expanduser("~"), ".agenteazy")
    os.makedirs(history_dir, exist_ok=True)
    return os.path.join(history_dir, "deploy-history.json")


def load_deploy_history() -> list:
    """Load the deploy history from ~/.agenteazy/deploy-history.json."""
    path = _get_history_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def record_deploy(name: str, version: str, url: str, modal_app_name: str) -> None:
    """Append a deploy record to the history file."""
    history = load_deploy_history()
    history.append({
        "name": name,
        "version": version,
        "url": url,
        "modal_app_id": modal_app_name,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    })
    path = _get_history_path()
    with open(path, "w") as f:
        json.dump(history, f, indent=2)
        f.write("\n")
