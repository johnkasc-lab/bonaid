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
