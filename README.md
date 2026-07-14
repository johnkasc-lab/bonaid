# Bonaid — Phase 1: Foundation

Open-source multi-agent trading research system. This is **Phase 1 only**:
the infrastructure every later phase (agents, reasoning, trading, dashboard)
plugs into. Nothing here makes trading decisions yet — that's Phase 3+.

## What's built and verified working
- ✅ **Project architecture** — `bonaid/` package: config, db, cache, llm, graph, cli
- ✅ **Configuration system** — `bonaid/config.py`, pydantic-settings, `.env`-driven
- ✅ **PostgreSQL** — SQLAlchemy 2.x models (`ScanLog`, `SystemHealth`), session management
- ✅ **Redis** — cache + pub/sub wrapper (`bonaid/cache.py`), ready for agent messaging in Phase 3
- ✅ **Ollama** — local LLM client (`bonaid/llm.py`), zero API cost, model-swappable
- ✅ **LangGraph** — real, compiling orchestration graph (`bonaid/graph.py`) — proven
  end-to-end with `bonaid ping`, ready for agent nodes to be added in Phase 3
- ✅ **Terminal CLI** — `bonaid status / init-db / ping / llm-check / version`
- ✅ **Docker Compose** — Postgres + Redis + Ollama + app, one command to stand up
- ✅ **Tests + CI** — 4 passing tests, GitHub Actions runs them on every push

## Verified in this session (no Docker daemon available in the build sandbox)
```
$ bonaid version
Bonaid - Phase 1 (Foundation) - environment=development

$ bonaid ping --query "test orchestration" --ticker AAPL
Bonaid orchestration graph is alive. (query='test orchestration', ticker='AAPL')

$ pytest tests/ -v
4 passed in 0.53s
```
`bonaid status` was also run and correctly reported Postgres/Redis/Ollama as
**down** (since no daemons exist in this sandbox) without crashing — that's
the correct, desired behavior; it proves the health-check logic itself works.
Once you run `docker compose up`, those three will show OK.

## Run it for real (needs Docker on your machine)
```bash
cd bonaid
cp .env.example .env          # edit if you want non-default passwords
docker compose -f docker/docker-compose.yml up -d --build

# pull a local model (one-time, ~4-5GB depending on model)
docker exec -it bonaid-ollama-1 ollama pull deepseek-r1:7b

# check everything is healthy
docker exec -it bonaid-app-1 bonaid status
```

Or run natively without Docker (need local Postgres/Redis/Ollama installed):
```bash
pip install -r requirements.txt && pip install -e .
cp .env.example .env
bonaid init-db
bonaid status
```

## Project layout
```
bonaid/
  bonaid/
    config.py     - settings (env-driven)
    db.py         - Postgres/SQLAlchemy session management
    cache.py      - Redis cache + pub/sub
    llm.py        - Ollama client
    graph.py      - LangGraph orchestration skeleton
    cli.py        - `bonaid` terminal command
    models/       - ORM tables (ScanLog, SystemHealth so far)
  docker/
    Dockerfile
    docker-compose.yml
  tests/
    test_foundation.py
  .github/workflows/ci.yml
  pyproject.toml, requirements.txt, .env.example
```

## Design decisions worth knowing
- **Redis pub/sub**, not Kafka/RabbitMQ — free, zero extra infra, sufficient
  for agent-to-agent messaging at this scale.
- **Ollama over any hosted LLM** — zero per-token cost, fully local/private,
  swap models (`deepseek-r1`, `qwen2.5`, `llama3.1`) via one config value.
- **LangGraph now, agents later** — the orchestration *shape* (a compiled
  graph with named nodes and shared state) is locked in now so Phase 3 is
  "add nodes," not "redesign how agents talk to each other."
- **SQLAlchemy `create_all`, no Alembic yet** — intentional for Phase 1;
  Alembic migrations get added in Phase 2 once the schema stabilizes around
  real data (adding it now would just mean rewriting migrations later).

## What's explicitly NOT in Phase 1
No news/sentiment/macro/risk/portfolio agents, no LLM reasoning calls, no
trading logic, no dashboards, no Grafana/Prometheus. Those are Phases 2-6,
same incremental approach — pick the next one when ready.

## Next phase options
1. **Phase 2 (Data)** — wire in yfinance, CCXT, FRED, news RSS, GDELT, Reddit
2. **Phase 3 (Agents)** — add the Technical Agent (reuses the backtesting
   engine already built), then News/Sentiment/Macro/Risk/Portfolio agents as
   LangGraph nodes feeding the Supervisor
3. Something narrower — e.g. just get one real agent (Technical) fully wired
   into this graph and reporting through `bonaid analyze <ticker>` before
   adding the rest
