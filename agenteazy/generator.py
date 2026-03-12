"""Agent JSON generator - Creates agent.json from repo analysis."""

import json
import os


def generate_agent_json(analysis) -> dict:
    """
    Generate an agent.json configuration from a RepoAnalysis object.

    Returns a dict suitable for serialization to agent.json.
    """
    entry = analysis.suggested_entry

    # Try to get a description from the entry point's docstring
    description = None
    if entry and entry.docstring:
        description = entry.docstring.split("\n")[0].strip()
    if not description:
        description = f"AI agent wrapping {analysis.repo_name}"

    config = {
        "name": analysis.repo_name,
        "description": description,
        "version": "0.1.0",
        "language": analysis.language,
        "entry": {
            "file": entry.file if entry else None,
            "function": entry.name if entry else None,
            "args": entry.args if entry else [],
        },
        "dependencies": {
            "file": "requirements.txt" if analysis.has_requirements_txt else None,
        },
        "verbs": ["ASK", "DO"],
    }

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
