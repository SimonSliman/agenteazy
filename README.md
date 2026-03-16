# AgentEazy

**Turn any Python utility into a callable AI tool in one command.**

Your code becomes a live API that any AI agent can find, call, and pay — without rewriting a single line.

[![PyPI](https://img.shields.io/pypi/v/agenteazy)](https://pypi.org/project/agenteazy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-82%20passing-brightgreen)]()

[Website](https://agenteazy.com) · [Dashboard](https://agenteazy.com/dashboard) · [Registry](https://agenteazy.com/agents) · [Docs](https://agenteazy.com/docs)

---

## Try it right now

No install needed. Call a live agent from your terminal:

```bash
curl -s -X POST https://simondusable--agenteazy-gateway-serve.modal.run/agent/zxcvbn-python/ \
  -H "Content-Type: application/json" \
  -d '{"verb":"DO","payload":{"data":{"password":"monkey123"}}}' | python3 -m json.tool
```

```json
{
  "status": "completed",
  "output": {
    "score": 1,
    "feedback": {
      "warning": "This is a very common password.",
      "suggestions": ["Add another word or two. Uncommon words are better."]
    }
  }
}
```

That's a real GitHub repo ([zxcvbn-python](https://github.com/dwolfhub/zxcvbn-python)), auto-wrapped and live. 18+ more in the registry.

---

## Deploy your own agent

```bash
pip install agenteazy
agenteazy signup your-github-username --email you@example.com
agenteazy deploy github.com/you/your-repo
```

Done. Your repo is live. Every AI agent on earth can now find and call it.

### What happens under the hood

1. **Analyze** — Clones the repo, parses the AST, detects the main public API function
2. **Wrap** — Generates a FastAPI wrapper that handles imports, dependencies, and dispatch
3. **Upload** — Pushes to serverless infrastructure (idle agents cost $0)
4. **Register** — Adds to the public registry so other agents can discover it

---

## Python SDK

```python
from agenteazy import AgentEazy

client = AgentEazy()

# Discover agents
agents = client.find("password strength")

# Call agents
result = client.do("zxcvbn-python", {"password": "monkey123"})
# → {"score": 1, "feedback": {"warning": "This is a very common password."}}

result = client.do("dateparser", {"date_string": "tomorrow at 3pm"})
# → "2026-03-17T15:00:00"

result = client.do("langdetect", {"text": "Bonjour le monde"})
# → "fr"

result = client.do("python-ftfy", {"text": "Ã©mile dupont"})
# → "émile dupont"

result = client.do("autopep8", {"source": "x=   1\nif  x==1:\n  print( 'hello' )"})
# → "x = 1\nif x == 1:\n    print('hello')\n"
```

---

## LangChain Integration

Every agent becomes a LangChain `BaseTool`:

```bash
pip install agenteazy[langchain]
```

```python
from agenteazy.integrations.langchain import AgentEazyTool, AgentEazyToolkit

tool = AgentEazyTool.from_agent("zxcvbn-python")
result = tool.invoke({"password": "test123"})

# Discover multiple tools from the registry
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
```

---

## Live Agent Registry

18 agents you can call right now, all auto-wrapped from real GitHub repos:

| Agent | What it does | Try it |
|-------|-------------|--------|
| [zxcvbn-python](https://github.com/dwolfhub/zxcvbn-python) | Password strength scoring | `{"password":"monkey123"}` → score 1/4 |
| [langdetect](https://github.com/Mimino666/langdetect) | Detect text language | `{"text":"Bonjour"}` → `"fr"` |
| [dateparser](https://github.com/scrapinghub/dateparser) | Parse natural language dates | `{"date_string":"tomorrow at 3pm"}` → datetime |
| [python-ftfy](https://github.com/rspeer/python-ftfy) | Fix broken Unicode | `{"text":"Ã©mile"}` → `"émile"` |
| [autopep8](https://github.com/hhatto/autopep8) | Format Python to PEP 8 | `{"source":"x=  1"}` → `"x = 1\n"` |
| [validators](https://github.com/python-validators/validators) | Validate emails, URLs, IPs | `{"value":"test@example.com"}` → `true` |
| [python-slugify](https://github.com/un33k/python-slugify) | Text to URL slug | `{"text":"Hello World!"}` → `"hello-world"` |
| [emoji](https://github.com/carpedm20/emoji) | Emojize/demojize text | `{"string":":thumbs_up:"}` → 👍 |
| [xmltodict](https://github.com/martinblech/xmltodict) | XML to JSON dict | `{"xml_input":"<a>1</a>"}` → `{"a":"1"}` |
| [mistune](https://github.com/lepture/mistune) | Fast Markdown → HTML | `{"s":"**bold**"}` → `"<strong>bold</strong>"` |
| [dateutil](https://github.com/dateutil/dateutil) | Parse date strings | `{"timestr":"March 5th 2024"}` → datetime |
| [arrow](https://github.com/arrow-py/arrow) | Date/time with timezone | `{}` → current datetime |
| [prettytable](https://github.com/jazzband/prettytable) | Parse HTML tables | HTML → structured rows |
| [python-markdown2](https://github.com/trentm/python-markdown2) | Markdown → HTML | `{"text":"# Hello"}` → `"<h1>Hello</h1>"` |
| [python-markdownify](https://github.com/matthewwithanm/python-markdownify) | HTML → Markdown | `{"html":"<h1>Hello</h1>"}` → `"# Hello"` |
| [num2words](https://github.com/savoirfairelinux/num2words) | Numbers to words | `{"number":42}` → `"forty-two"` |
| [shortuuid](https://github.com/skorokithakis/shortuuid) | Generate short UUIDs | `{}` → `"N6nquzbtjAF..."` |
| [humanize](https://github.com/python-humanize/humanize) | Natural language lists | `{"items":["Alice","Bob"]}` → `"Alice and Bob"` |

Browse all at [agenteazy.com/agents](https://agenteazy.com/agents).

---

## What repos work best

AgentEazy auto-detects the right entry point for stateless Python utilities — functions that take input and return output.

| Works great | Examples |
|------------|---------|
| Text processing | slugify, ftfy, emoji, markdown2 |
| Validation & parsing | validators, dateparser, dateutil |
| Security tools | zxcvbn (passwords), nh3 (HTML sanitization) |
| Code formatting | autopep8 |
| Data conversion | xmltodict, markdownify, num2words |
| Language detection | langdetect |

| Needs `--entry` flag | Why |
|---------------------|-----|
| Large repos with many functions | Auto-detect may pick a helper instead of the main API |
| Class-based APIs | Specify `--entry "file.py:Class.method"` |

| Not a good fit | Why |
|----------------|-----|
| HTTP clients (requests, boto3) | They make outbound calls, not pure functions |
| Frameworks (Flask, Django) | Already have their own endpoints |
| Heavy ML models | Cold start too slow for serverless |

Override the entry point when needed:

```bash
agenteazy deploy github.com/you/repo --entry "mypackage/core.py:process"
agenteazy deploy github.com/you/repo --entry "mypackage/model.py:MyClass.predict"
```

---

## TollBooth — Agent Credits

Agents can charge credits per call. Set a price and the gateway handles billing.

```bash
agenteazy deploy github.com/you/your-repo --price 10
```

- **Free by default** — no credits needed to call free agents
- **You set the price** — 1 credit, 10, 100 — your choice
- **80/20 split** — you keep 80%, platform takes 20% for infrastructure
- **50 free credits** on signup, buy more at [agenteazy.com/dashboard](https://agenteazy.com/dashboard)

---

## AgentLang — 10 Universal Verbs

One protocol for all agents. One HTTP POST, one envelope:

```json
POST /agent/{name}/
{"verb": "DO", "payload": {"data": {"input": "hello"}}}
```

| Verb | What it does | Status |
|------|-------------|--------|
| **DO** | Execute the agent's main function | Live ✅ |
| **ASK** | Query capabilities and parameters | Live ✅ |
| **FIND** | Search the registry for agents | Live ✅ |
| **PAY** | Transfer credits between agents | Live ✅ |
| **SHARE** | Pass context between calls | Live ✅ |
| **REPORT** | Get audit log | Live ✅ |
| **STOP** | Halt a running task | Live ✅ |
| WATCH | Subscribe to events | Planned |
| TRUST | Authenticated sessions | Planned |
| LEARN | Ingest new knowledge | Planned |

---

## CLI Reference

```bash
# Deploy
agenteazy deploy <repo>                    # Full pipeline
agenteazy deploy <repo> --local            # Test locally first
agenteazy deploy <repo> --price 10         # Paid agent
agenteazy deploy <repo> --entry "f.py:fn"  # Override entry point
agenteazy deploy <repo> --env KEY=VALUE    # Inject env vars

# Analyze & Wrap
agenteazy analyze <repo>                   # Inspect without deploying
agenteazy wrap <repo>                      # Generate wrapper only
agenteazy batch-deploy <repos.txt>         # Deploy from file

# Account
agenteazy signup <username> --email <email>  # Get API key + 50 credits
agenteazy balance                            # Check credits
agenteazy transactions                       # View history

# Registry
agenteazy search "query"                   # Find agents
agenteazy list                             # List all agents
agenteazy status                           # Health check
```

---

## Architecture

```
agenteazy deploy <repo>
    │
    ├── ANALYZE  → Clone, parse AST, detect public API function
    ├── WRAP     → Generate FastAPI wrapper with full import handling
    ├── UPLOAD   → Push to serverless volume (idle = $0)
    ├── REGISTER → Add to searchable registry
    └── LIVE     → Callable at gateway/agent/{name}/

Gateway (serves all agents)  ←→  Registry (search + credits)
    │                                    │
    └── Agent Volume                     └── TollBooth
        /agents/zxcvbn-python/               Signup, balance,
        /agents/langdetect/                  deduct, earn, transfer
        /agents/dateparser/
        ... (36 agents)
```

---

## Contributing

Best first contribution: **OpenAI Function Calling integration**. Same pattern as the LangChain wrapper — one file, self-contained. See `agenteazy/integrations/langchain.py` as a template.

```bash
git clone https://github.com/SimonSliman/agenteazy
cd agenteazy
pip install -e ".[dev]"
pytest tests/ -q  # 82 tests
```

---

## License

MIT
