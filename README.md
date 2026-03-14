# AgentEazy

**Turn any GitHub repo into an interoperable AI agent in one command.**

Open source · MIT Licensed · [agenteazy.com](https://agenteazy.com)

## Quick Start

```bash
pip install agenteazy
agenteazy signup <your-github-username>
agenteazy deploy github.com/you/your-repo
```

Your repo is now a live agent. Call it:

```bash
curl -X POST https://gateway.agenteazy.com/agent/your-repo/ \
  -H "Content-Type: application/json" \
  -d '{"verb":"DO","payload":{"data":{"input":"hello"}}}'
```

## What is AgentEazy?

AgentEazy wraps any Python repository as a discoverable, callable AI agent that speaks a universal 10-verb protocol (AgentLang). No rewrite. No SDK. Just one command.

- Analyzes your repo with AST parsing (no code execution)
- Generates an agent.json manifest and FastAPI wrapper
- Deploys to a serverless gateway
- Registers in a public directory so other agents can find yours

## CLI Commands

| Command | Description |
|---------|-------------|
| `agenteazy analyze <repo>` | Detect language, deps, entry point |
| `agenteazy wrap <repo>` | Generate agent.json + wrapper |
| `agenteazy deploy <repo>` | Deploy to gateway + register |
| `agenteazy deploy <repo> --local` | Test locally |
| `agenteazy deploy <repo> --price 10` | Deploy as paid agent (10 credits/call) |
| `agenteazy signup <username>` | Create account, get API key |
| `agenteazy balance` | Check credit balance |
| `agenteazy transactions` | View transaction history |
| `agenteazy search "query"` | Search agent registry |
| `agenteazy list` | List all registered agents |
| `agenteazy status` | Show deployment status |
| `agenteazy gateway deploy` | Deploy gateway infrastructure |
| `agenteazy gateway status` | Gateway health check |
| `agenteazy registry deploy` | Deploy registry infrastructure |
| `agenteazy registry start` | Run registry locally |
| `agenteazy stop <name>` | Stop a deployed agent |
| `agenteazy logs <name>` | View agent logs |
| `agenteazy batch-deploy <dir>` | Deploy multiple repos |

## AgentLang — 10 Universal Verbs

Every agent speaks the same protocol. One HTTP POST, one envelope:

```json
{"verb": "DO", "auth": null, "payload": {"task": "process", "data": {"input": "hello"}}}
```

| Verb | Purpose |
|------|---------|
| DO | Execute a task |
| ASK | Query capabilities |
| FIND | Search the registry |
| PAY | Transfer credits between agents |
| SHARE | Pass context to an agent |
| REPORT | Get audit log |
| WATCH | Subscribe to events |
| STOP | Halt a running task |
| TRUST | Establish authenticated session |
| LEARN | Ingest new knowledge |

## TollBooth — Agent Credits

Agents can charge credits per call. Developers earn 80%, platform keeps 20% for infrastructure.

```bash
agenteazy deploy github.com/you/ml-model --price 10
```

No billing code needed. Set a price and the gateway handles everything. Sign in at [agenteazy.com](https://agenteazy.com) to manage your balance.

## Architecture

```
agenteazy deploy <repo>
│
├── 1. ANALYZE  → Clone, detect Python, parse AST
├── 2. WRAP     → Generate agent.json + FastAPI wrapper
├── 3. UPLOAD   → Push to serverless volume
├── 4. REGISTER → Add to public registry
└── 5. LIVE     → Callable at gateway/agent/{name}/

Gateway (1 endpoint) ──── Registry (SQLite)
│                         │
└── Agent Volume          └── TollBooth (credits)
    /agents/repo-a/           /tollbooth/balance
    /agents/repo-b/           /tollbooth/deduct
    /agents/repo-c/           /tollbooth/earn
```

## Dashboard

Sign in at [agenteazy.com](https://agenteazy.com) with GitHub to manage your agents, view your balance, and track activity.

## Contributing

We welcome contributions:

1. Open an issue describing what you want to build or fix
2. We'll discuss the approach together
3. Clone the repo and create a feature branch
4. Submit a Pull Request referencing the issue

Questions? Open an issue or email hello@agenteazy.com

## License

MIT — see [LICENSE](LICENSE) for details.
