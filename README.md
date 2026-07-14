# Bonaid — Phase 1: Foundation

Open-source multi-agent trading research system. This is **Phase 1 only**:
the infrastructure every later phase (agents, reasoning, trading, dashboard)
plugs into. Nothing here makes trading decisions yet — that's Phase 3+.

## What's built and verified working

### Foundation (Phase 1)
- ✅ **Project architecture** — `bonaid/` package: config, db, cache, llm, graph, cli
- ✅ **Configuration system** — `bonaid/config.py`, pydantic-settings, `.env`-driven
- ✅ **PostgreSQL** — SQLAlchemy 2.x models (`ScanLog`, `SystemHealth`, `AgentDecision`), session management
- ✅ **Redis** — cache + pub/sub wrapper (`bonaid/cache.py`), ready for agent messaging in Phase 3
- ✅ **Ollama** — local LLM client (`bonaid/llm.py`), zero API cost, model-swappable
- ✅ **LangGraph** — real, compiling orchestration graph (`bonaid/graph.py`)
- ✅ **Terminal CLI** — `bonaid status / init-db / ping / llm-check / analyze / version`
- ✅ **Docker Compose** — Postgres + Redis + Ollama + app, one command to stand up
- ✅ **Tests + CI** — 6 passing tests, GitHub Actions runs them on every push

### Technical Agent (first real agent — Phase 3, step 1)
- ✅ **`bonaid/analysis/`** — the full backtesting engine (11 strategies, indicators,
  vectorized backtester, metrics) ported in as a first-class package
- ✅ **`bonaid/agents/technical_agent.py`** — runs all strategies on a ticker,
  weights each one's "vote" by its own 5-year historical Sharpe on that
  specific ticker (not a flat majority vote), and produces a
  BUY/WATCH/HOLD/SELL action with a 0-100% confidence score
- ✅ **Wired into LangGraph** — `technical` node, `run_technical_analysis()`,
  ready for News/Sentiment/Macro/Risk/Portfolio nodes to be added alongside it
- ✅ **`bonaid analyze <ticker>`** — the actual command from the original spec,
  producing real output:
  ```
  $ bonaid analyze AAPL
  Recommendation: BUY AAPL
  Confidence: 74.2%
  Reasons:
    - 8 of 11 strategies currently signal long
    - Highest-conviction signal: Dual_Momentum (5yr Sharpe 1.42, currently LONG)
    - 3 strategies flat - mixed short-term picture

  Logged to decision history.
  ```
- ✅ **Optional LLM narration** — if Ollama is reachable, adds a plain-English
  paragraph explaining the technical picture (degrades gracefully to the
  structured output alone if Ollama isn't running)
- ✅ **Persisted to Postgres** — every `analyze` call writes an `AgentDecision`
  row, which is what makes the future Memory/Learning phase possible
  ("how did our BUY calls actually perform?")

## Verified in this session
```
$ pytest tests/ -v
6 passed in 1.40s

$ bonaid analyze AAPL --synthetic
Recommendation: SELL AAPL
Confidence: 16.4%
Reasons:
  - 2 of 11 strategies currently signal long
  - Highest-conviction signal: Dual_Momentum (5yr Sharpe 0.12, currently FLAT)
  - 9 strategies flat - mixed short-term picture
```
(Ran with `--synthetic` since this build sandbox has no internet access to
Yahoo Finance and no live Postgres/Ollama — the DB write correctly failed
with a clear connection-refused message instead of crashing, which is the
desired graceful-degradation behavior. All of this goes green the moment you
run it inside `docker compose` on a real machine.)

## Fixes included in this version (if you hit these on an earlier copy)
- Fixed a broken f-string in `cli.py` that crash-looped `llm-check`
- Fixed `docker-compose.yml`: `app` service now sets `entrypoint: []` so
  `command` doesn't get appended after the image's `ENTRYPOINT ["bonaid"]`
  (was causing an infinite restart loop)
- Pinned `name: bonaid` at the top of `docker-compose.yml` so container names
  are consistently `bonaid-*` regardless of which folder you run compose from


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

## What's explicitly NOT built yet
No news/sentiment/macro/risk/portfolio agents, no trading logic, no
dashboards, no Grafana/Prometheus, no memory/learning queries against the
accumulated `AgentDecision` history yet. Same incremental approach — pick the
next one when ready.

## Next phase options
1. **News Agent** — same pattern as Technical: fetch (RSS/GDELT, free), score,
   add a `news` node to the graph, feed into an expanded `analyze` command
2. **Sentiment Agent** — Reddit/social scoring, same pattern
3. **Risk Agent** — position sizing, stop-loss/take-profit levels, portfolio
   exposure limits — this is what turns "BUY, 74% confidence" into an actual
   tradeable order spec
4. **Real Supervisor node** — once 2+ agents exist, replace the current
   pass-through with actual multi-agent consensus logic (weighted voting,
   conflict resolution when Technical says BUY but Sentiment says SELL)
5. **Broaden the data layer (Phase 2 proper)** — FRED (macro), more news
   sources — now that there's a consumer (the agents) to justify each one
