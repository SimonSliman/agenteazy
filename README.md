# AgentEazy

> Turn any GitHub repo into an interoperable AI agent in one command.

AgentEazy analyzes a GitHub repository, detects its structure, generates a FastAPI wrapper, and deploys it as a fully interoperable agent with a universal verb-based protocol (AgentLang).

## Quick Start

```bash
# Install
pip install agenteazy

# Sign up for an account
agenteazy signup <github_username> --email you@example.com

# Deploy your first agent
agenteazy deploy user/repo
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `agenteazy analyze <repo>` | Clone and analyze a GitHub repo's structure |
| `agenteazy wrap <repo>` | Generate agent.json + FastAPI wrapper |
| `agenteazy deploy <repo>` | Analyze, wrap, and deploy an agent |
| `agenteazy deploy <repo> --local` | Deploy locally for testing |
| `agenteazy deploy <repo> --price N` | Deploy with per-call credit pricing |
| `agenteazy deploy <repo> --legacy` | Deploy as standalone Modal app |
| `agenteazy test --url <url>` | Test all endpoints of a running agent |
| `agenteazy search <query>` | Search for agents in the registry |
| `agenteazy list` | List all agents in the registry |
| `agenteazy status` | Show Modal auth and deployed agents |
| `agenteazy stop <name>` | Stop a deployed Modal agent |
| `agenteazy logs <name>` | Show logs for a deployed agent |
| `agenteazy batch-deploy <dir>` | Wrap and deploy all repos in a directory |
| `agenteazy cleanup` | List and remove deployed Modal apps |
| `agenteazy signup` | Sign up and get an API key |
| `agenteazy balance` | Check your credit balance |
| `agenteazy transactions` | Show recent transactions |
| `agenteazy registry start` | Start the registry server locally |
| `agenteazy registry deploy` | Deploy the registry to Modal |
| `agenteazy gateway deploy` | Deploy the single gateway to Modal |
| `agenteazy gateway status` | Show gateway URL and health |

## AgentLang: 10-Verb Protocol

AgentLang is a universal protocol for agent-to-agent communication. Every agent speaks the same 10 verbs:

| Verb | Description | Example |
|------|-------------|---------|
| `ASK` | Query without changing state | `{"verb": "ASK"}` → returns capabilities |
| `DO` | Execute a task | `{"verb": "DO", "payload": {"data": {"text": "hello"}}}` |
| `FIND` | Search for agents or data | `{"verb": "FIND", "payload": {"data": "sentiment"}}` |
| `PAY` | Transfer credits for service | `{"verb": "PAY", "payload": {"data": {"to_agent": "x", "credits": 10}}}` |
| `WATCH` | Subscribe to changes | `{"verb": "WATCH"}` → webhook subscription |
| `STOP` | Halt current task | `{"verb": "STOP"}` → cancels running work |
| `TRUST` | Establish authenticated session | `{"verb": "TRUST"}` → AgentPass handshake |
| `SHARE` | Pass context between agents | `{"verb": "SHARE", "payload": {"data": {"key": "value"}}}` |
| `LEARN` | Ingest new knowledge | `{"verb": "LEARN", "payload": {"data": {...}}}` |
| `REPORT` | Get audit log of actions | `{"verb": "REPORT"}` → returns call history |

All verbs are sent via `POST /agent/{name}/` with a JSON body containing `verb` and `payload`.

## TollBooth: Agent Billing

Agents can charge credits per call using the TollBooth billing system:

- Deploy a paid agent: `agenteazy deploy user/repo --price 5`
- Callers pass their API key via `auth` field or `x-api-key` header
- 80% of credits go to the agent developer, 20% platform fee
- Agents can pay each other using the `PAY` verb
- Free agents work without authentication

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   CLI        │────▶│   Gateway    │────▶│   Agents     │
│  (typer)     │     │  (FastAPI)   │     │  (on Volume) │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │   Registry   │
                     │  (FastAPI +  │
                     │   SQLite)    │
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │  TollBooth   │
                     │  (billing)   │
                     └──────────────┘

CLI ─── analyzes repos, generates wrappers, deploys agents
Gateway ─── single FastAPI app routing all agent requests
Registry ─── agent discovery, search, ownership tracking
TollBooth ─── credit balances, billing, developer payouts
Modal ─── serverless infrastructure (volumes + web endpoints)
```

## Links

- **Docs:** [agenteazy.com](https://agenteazy.com)
- **Dashboard:** [agenteazy.com/dashboard](https://agenteazy.com/dashboard)

## License

MIT — see [LICENSE](LICENSE) for details.

*Note: License may change to BSL (Business Source License) in a future release.*

## Contributing

Contributions are welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to your branch and open a Pull Request

For bugs and feature requests, open an issue on GitHub.
