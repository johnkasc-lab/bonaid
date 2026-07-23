"""
bonaid/models/base.py
Foundation tables. Later phases add: positions, orders, agent_decisions,
news_items, sentiment_scores, macro_series, etc. - all in this same
models/ package, all sharing the one `Base` from bonaid.db.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON
from bonaid.db import Base


class ScanLog(Base):
    """Every agent run (manual or scheduled) records one row here.
    This is the audit trail / 'memory' foundation - later phases (Memory &
    Learning) query this table to learn from past decisions."""
    __tablename__ = "scan_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    agent = Column(String(64), index=True)       # e.g. "technical", "news", "supervisor"
    ticker = Column(String(32), index=True, nullable=True)
    market = Column(String(16), nullable=True)   # "US" | "INDIA"
    action = Column(String(32), nullable=True)   # e.g. "BUY", "SELL", "HOLD", "SCAN"
    confidence = Column(Float, nullable=True)
    details = Column(JSON, nullable=True)        # free-form structured payload
    notes = Column(Text, nullable=True)


class AgentDecision(Base):
    """One row per `bonaid analyze <ticker>` run. This is the structured
    record later agents (Risk, Portfolio, Supervisor) and the Memory/Learning
    phase will query - e.g. 'how did our BUY calls on AAPL perform after 30
    days?' becomes possible once enough of these accumulate."""
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(32), index=True)
    action = Column(String(16))          # "BUY" | "SELL" | "HOLD" | "WATCH"
    confidence = Column(Float)           # 0-100
    reasons = Column(JSON)               # list of strings, the "check/x ..." lines
    signal_breakdown = Column(JSON)      # per-strategy raw signal + historical Sharpe
    llm_summary = Column(Text, nullable=True)  # optional natural-language explanation from Ollama
    news_assessment = Column(JSON, nullable=True)  # headline sentiment from the News Agent
    sentiment_assessment = Column(JSON, nullable=True)  # Reddit social sentiment from the Sentiment Agent
    supervisor_decision = Column(JSON, nullable=True)  # reconciled final action + reasoning
    risk_assessment = Column(JSON, nullable=True)  # position size, stop-loss, take-profit from the Risk Agent


class PaperPosition(Base):
    """A simulated (paper) trade position. Opened when the Supervisor
    decides BUY and Risk Agent sizes it (auto, unless --manual was passed
    to `bonaid analyze`). Closed automatically by `bonaid check-positions`
    when the live price crosses the stop-loss or take-profit level set at
    entry, or manually via `bonaid close`."""
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(32), index=True)
    shares = Column(Integer)
    entry_price = Column(Float)
    entry_date = Column(DateTime, default=datetime.utcnow)
    entry_confidence = Column(Float, nullable=True)  # Supervisor's confidence at the time this was opened
    source_decision_id = Column(Integer, nullable=True, index=True)  # links back to the AgentDecision that opened this - not a hard FK (positions/decisions can outlive each other independently), just a soft reference for attribution analytics
    stop_loss = Column(Float)
    take_profit = Column(Float)
    status = Column(String(16), default="OPEN", index=True)  # "OPEN" | "CLOSED"
    exit_price = Column(Float, nullable=True)
    exit_date = Column(DateTime, nullable=True)
    exit_reason = Column(String(32), nullable=True)  # "stop_loss" | "take_profit" | "manual"
    realized_pnl = Column(Float, nullable=True)


class MLModel(Base):
    """A trained version of the self-learning outcome predictor. Weights
    are stored as plain JSON (a list of floats + a bias), not a pickled/
    binary blob - deliberately auditable, a human can read the actual
    learned coefficients directly from the database. Only the most recent
    row is used for predictions (bonaid.ml.outcome_model.load_latest_model),
    older rows are kept as a version history."""
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True)
    trained_at = Column(DateTime, default=datetime.utcnow, index=True)
    feature_names = Column(JSON)
    weights = Column(JSON)
    bias = Column(Float)
    train_accuracy = Column(Float)
    trade_count = Column(Integer)
    notes = Column(Text, nullable=True)


class ErrorLog(Base):
    """Captured failures from data-fetching agents (StockTwits/Reddit/
    yfinance/FRED timeouts, rate limits, unsupported symbols, etc.) -
    previously these only ever went to stdout (the [agent_name] print
    lines you've seen throughout `bonaid analyze`/`scan` output). Storing
    them lets `bonaid diagnose` aggregate and classify what's actually
    been failing, rather than scrolling back through terminal history."""
    __tablename__ = "error_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    component = Column(String(64), index=True)   # e.g. "sentiment_agent", "data_fetcher", "macro_agent"
    ticker = Column(String(32), nullable=True)
    message = Column(Text)


class SystemHealth(Base):
    """Heartbeat table - `bonaid status` reads this to show whether each
    subsystem (db, redis, ollama, data feed) is reachable and when it was
    last successfully checked."""
    __tablename__ = "system_health"

    id = Column(Integer, primary_key=True)
    component = Column(String(64), unique=True, index=True)  # "postgres","redis","ollama",...
    status = Column(String(16))                                # "ok" | "degraded" | "down"
    last_checked = Column(DateTime, default=datetime.utcnow)
    detail = Column(Text, nullable=True)
