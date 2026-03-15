# AgentEazy

**Turn any GitHub repo into an interoperable AI agent in one command.**

Open source · MIT Licensed · [agenteazy.com](https://agenteazy.com)

---

## Quick Start

```bash
pip install agenteazy
agenteazy signup <your-github-username>
agenteazy deploy github.com/you/your-repo
```

Your repo is now a live agent. Call it:

```bash
curl -X POST https://simondusable--agenteazy-gateway-serve.modal.run/agent/your-repo/ \
  -H "Content-Type: application/json" \
  -d '{"verb":"DO","payload":{"data":{"input":"hello"}}}'
```

---

## Python SDK

```bash
pip install agenteazy
```

```python
from agenteazy import AgentEazy

client = AgentEazy()

# Search for agents
agents = client.find("password strength")

# Call an agent
result = client.do("zxcvbn-python", {"password": "test123"})
print(result)
```

---

## LangChain Integration

```bash
pip install agenteazy[langchain]
```

```python
from agenteazy.integrations.langchain import AgentEazyTool, AgentEazyToolkit

# Single tool from one agent
tool = AgentEazyTool.from_agent("zxcvbn-python")
result = tool.run({"password": "test123"})

# Toolkit — multiple tools from a registry search
toolkit = AgentEazyToolkit()
tools = toolkit.get_tools(query="text processing", limit=5)
```

---

## CrewAI Integration

```bash
pip install agenteazy[crewai]
```

```python
from agenteazy.integrations.crewai import AgentEazyCrewTool

tool = AgentEazyCrewTool.from_agent("zxcvbn-python")
result = tool.run({"password": "test123"})
```

---

## CLI Commands

### Core

| Command | Description |
|---------|-------------|
| `agenteazy analyze <repo>` | Detect language, deps, entry point |
| `agenteazy wrap <repo>` | Generate agent.json + FastAPI wrapper |
| `agenteazy wrap <repo> --entry func` | Specify entry function |
| `agenteazy wrap <repo> --env KEY=VAL` | Set environment variables |
| `agenteazy deploy <repo>` | Deploy to gateway + register |
| `agenteazy deploy <repo> --local` | Test locally on port 8000 |
| `agenteazy deploy <repo> --price 10` | Deploy as paid agent (10 credits/call) |

### Batch

| Command | Description |
|---------|-------------|
| `agenteazy batch-analyze <dir>` | Analyze all repos in a directory |
| `agenteazy batch-deploy <dir>` | Deploy multiple repos at once |
| `agenteazy batch-deploy <dir> --wrap-only` | Wrap without deploying |
| `agenteazy batch-deploy <dir> --dry-run` | Preview without changes |
| `agenteazy batch-deploy <dir> --entry-file main.py` | Override entry file |
| `agenteazy batch-deploy <dir> --skip-existing` | Skip already-deployed agents |
| `agenteazy batch-deploy <dir> --max-failures 3` | Stop after N failures |

### Account

| Command | Description |
|---------|-------------|
| `agenteazy signup <username>` | Create account, get API key |
| `agenteazy balance` | Check credit balance |
| `agenteazy transactions` | View transaction history |

### Registry

| Command | Description |
|---------|-------------|
| `agenteazy search "query"` | Search agent registry |
| `agenteazy list` | List all registered agents |
| `agenteazy status` | Show deployment status |

### Environment Variables

| Command | Description |
|---------|-------------|
| `agenteazy env list` | List configured env vars |
| `agenteazy env set KEY VAL` | Set an environment variable |
| `agenteazy env remove KEY` | Remove an environment variable |

### Infrastructure

| Command | Description |
|---------|-------------|
| `agenteazy gateway deploy` | Deploy gateway to Modal |
| `agenteazy gateway status` | Gateway health check |
| `agenteazy registry deploy` | Deploy registry to Modal |
| `agenteazy registry start` | Run registry locally |
| `agenteazy stop <name>` | Stop a deployed agent |
| `agenteazy logs <name>` | View agent logs |

---

## AgentLang — 10 Universal Verbs

Every agent speaks the same protocol. One HTTP POST, one envelope:

```json
{"verb": "DO", "payload": {"data": {"input": "hello"}}}
```

| Verb | Purpose | Status |
|------|---------|--------|
| DO | Execute a task | Working ✅ |
| ASK | Query capabilities | Working ✅ |
| FIND | Search the registry | Working ✅ |
| PAY | Transfer credits between agents | Working ✅ |
| SHARE | Pass context to an agent | Working ✅ |
| REPORT | Get audit log and recent calls | Working ✅ |
| STOP | Halt a running task | Working ✅ |
| WATCH | Subscribe to events | Stub 🔜 |
| TRUST | Establish authenticated session | Stub 🔜 |
| LEARN | Ingest new knowledge | Stub 🔜 |

---

## TollBooth — Agent Credits

Agents can charge credits per call. Developers earn 80%, platform keeps 20% for infrastructure.

```bash
agenteazy deploy github.com/you/ml-model --price 10
```

No billing code needed. Set a price and the gateway handles everything.

- **Free agents**: 0 credits per call (default)
- **Paid agents**: Set any price with `--price`
- **Revenue split**: 80% to agent developer, 20% platform fee
- **Top up**: `agenteazy balance` to check, credits added via signup

---

## Architecture

```
Developer: agenteazy deploy <repo>
    |
    |-- 1. ANALYZE  -> Clone, detect Python, parse AST
    |-- 2. WRAP     -> Generate agent.json + FastAPI wrapper
    |-- 3. UPLOAD   -> Push to serverless volume
    |-- 4. REGISTER -> Add to public registry
    +-- 5. LIVE     -> Callable at gateway/agent/{name}/

Gateway (1 endpoint) ---- Registry (SQLite)
    |                          |
    +-- Agent Volume           +-- TollBooth (credits)
        /agents/repo-a/            /tollbooth/balance
        /agents/repo-b/            /tollbooth/deduct
        /agents/repo-c/            /tollbooth/earn
```

---

## Supported Repo Types

| Type | Supported |
|------|-----------|
| `requirements.txt` | ✅ |
| `pyproject.toml` | ✅ |
| `setup.py` | ✅ |
| Class-based agents | ✅ |
| `src/` layout | ✅ |
| Environment variables | ✅ |

---

## Contributing

We welcome contributions:

1. Open an issue describing what you want to build or fix
2. We'll discuss the approach together
3. Clone the repo and create a feature branch
4. Submit a Pull Request referencing the issue

Questions? Open an issue or email hello@agenteazy.com

## License

MIT — see [LICENSE](LICENSE) for details.
