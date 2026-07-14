"""
bonaid/agents/technical_agent.py
The first real agent. Given a ticker:
  1. Fetches 5yr OHLCV data (yfinance, real; or synthetic for offline testing)
  2. Runs every strategy in the analysis engine
  3. Backtests each to get its historical Sharpe on THIS specific ticker
     (a strategy that's great on TSLA might be mediocre on JNJ - weighting
     by per-ticker historical performance, not a flat vote, is what makes
     the confidence score meaningful rather than arbitrary)
  4. Aggregates into a single BUY/SELL/HOLD/WATCH action + confidence score
  5. Optionally asks the local LLM (Ollama) to write a one-paragraph plain-
     English summary of the technical picture

This is deliberately NOT a full trading decision - no risk sizing, no stop
loss/take profit, no macro/news/sentiment context yet. Those are Risk,
Portfolio, News, Sentiment, Macro agents in later phases, which this same
agent's output will feed into via the Supervisor.
"""
from dataclasses import dataclass, field
import pandas as pd

from bonaid.analysis.strategies import STRATEGY_REGISTRY
from bonaid.analysis.backtester import run_backtest
from bonaid.analysis.metrics import summarize


@dataclass
class TechnicalAnalysis:
    ticker: str
    action: str
    confidence: float
    reasons: list = field(default_factory=list)
    signal_breakdown: list = field(default_factory=list)  # [{strategy, signal, sharpe}, ...]


def analyze_ticker(ticker: str, df: pd.DataFrame) -> TechnicalAnalysis:
    """Core logic: no I/O, no LLM call - pure function, easy to unit test."""
    breakdown = []
    long_votes = 0
    weighted_score = 0.0
    total_weight = 0.0

    for strat_name, strat_fn in STRATEGY_REGISTRY.items():
        if strat_name == "Buy_and_Hold":
            continue
        try:
            signal = strat_fn(df)
            current_signal = int(signal.iloc[-1])
            result = run_backtest(df, signal)
            m = summarize(result["equity_curve"], result["returns"], result["trades"])
            sharpe = m["Sharpe"]

            # Weight each strategy's "vote" by its own historical Sharpe on
            # THIS ticker, floored at 0 so a historically bad strategy
            # doesn't get to argue against the others with negative weight
            # (it just gets ignored, not treated as evidence for the opposite).
            weight = max(sharpe, 0.0) + 0.1  # +0.1 floor so nothing gets zero say
            if current_signal == 1:
                long_votes += 1
                weighted_score += weight
            total_weight += weight

            breakdown.append({
                "strategy": strat_name,
                "signal": "LONG" if current_signal == 1 else "FLAT",
                "sharpe_5y": sharpe,
            })
        except Exception as e:
            breakdown.append({"strategy": strat_name, "signal": "ERROR", "sharpe_5y": None, "error": str(e)})

    n_strategies = len([b for b in breakdown if b["signal"] != "ERROR"])
    confidence = float(round((weighted_score / total_weight) * 100, 1)) if total_weight > 0 else 0.0

    if confidence >= 65:
        action = "BUY"
    elif confidence >= 45:
        action = "WATCH"
    elif confidence >= 25:
        action = "HOLD"
    else:
        action = "SELL"

    breakdown_sorted = sorted(
        [b for b in breakdown if b.get("sharpe_5y") is not None],
        key=lambda b: b["sharpe_5y"], reverse=True
    )
    reasons = [f"{long_votes} of {n_strategies} strategies currently signal long"]
    if breakdown_sorted:
        top = breakdown_sorted[0]
        reasons.append(
            f"Highest-conviction signal: {top['strategy']} "
            f"(5yr Sharpe {top['sharpe_5y']}, currently {top['signal']})"
        )
    flat_count = n_strategies - long_votes
    if flat_count > 0:
        reasons.append(f"{flat_count} strategies flat - mixed short-term picture")

    return TechnicalAnalysis(
        ticker=ticker,
        action=action,
        confidence=confidence,
        reasons=reasons,
        signal_breakdown=breakdown,
    )


def summarize_with_llm(analysis: TechnicalAnalysis) -> str | None:
    """Optional: ask the local Ollama model to phrase the technical picture
    in one plain-English paragraph. Returns None if Ollama isn't reachable -
    the structured analysis above is always available even without it."""
    from bonaid import llm
    if not llm.is_available():
        return None

    breakdown_lines = "\n".join(
        f"- {b['strategy']}: {b['signal']} (5yr Sharpe {b.get('sharpe_5y')})"
        for b in analysis.signal_breakdown if b["signal"] != "ERROR"
    )
    prompt = (
        f"You are a technical analysis assistant. Given this data for {analysis.ticker}, "
        f"write ONE short plain-English paragraph (3-4 sentences max) summarizing the "
        f"technical picture. Be factual and measured, not hyped. Do not give financial advice "
        f"or a definitive buy/sell instruction - describe what the indicators show.\n\n"
        f"Aggregate action: {analysis.action}, confidence: {analysis.confidence}%\n"
        f"Per-strategy signals:\n{breakdown_lines}"
    )
    try:
        return llm.generate(prompt).strip()
    except Exception:
        return None
