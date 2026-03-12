# AgentEazy

**Turn any GitHub repo into an AI agent in one command.**

AgentEazy analyzes a GitHub repository, detects its structure, and generates a FastAPI wrapper that exposes the repo's functionality as an agent with standardized endpoints.

## Install

```bash
pip install -e .
```

## Usage

### Analyze a repo

```bash
agenteazy analyze pallets/markupsafe
```

Clones the repo and shows detected language, dependencies, functions, and suggested entry point.

### Wrap a repo

```bash
agenteazy wrap pallets/markupsafe
```

Analyzes the repo, generates `agent.json`, a FastAPI `wrapper.py`, and `requirements.txt` in `./agenteazy-output/{repo_name}/`.

### Test locally

```bash
cd agenteazy-output/markupsafe
pip install -r requirements.txt
python wrapper.py
```

Then visit `http://localhost:8000/` for agent info, or `POST /do` to execute the entry function.

## Commands

| Command | Description |
|---------|-------------|
| `agenteazy analyze <repo>` | Analyze a GitHub repo |
| `agenteazy wrap <repo>` | Generate agent.json + FastAPI wrapper |
| `agenteazy deploy <repo>` | Deploy to cloud (coming soon) |
| `agenteazy search <query>` | Search agents (coming soon) |

## How it works

1. **Analyze** — Clones the repo, detects Python files, parses functions with AST, reads dependencies, and scores potential entry points.
2. **Generate** — Creates an `agent.json` config describing the agent's name, entry point, args, and supported verbs (`ASK`, `DO`).
3. **Wrap** — Produces a self-contained FastAPI server with endpoints for health checks, capability discovery, and function execution.

## License

MIT
