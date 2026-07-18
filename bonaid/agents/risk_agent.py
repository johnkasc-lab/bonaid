"""
bonaid/agents/risk_agent.py
Second real agent. Given a Technical Agent's output plus the underlying
price data, this computes:
  - Stop-loss: ATR-based, not a fixed %, so it adapts to each ticker's own
    volatility (a 2% stop on a calm utility stock is very different risk
    than a 2% stop on a volatile small-cap).
  - Take-profit: derived from the stop distance via a fixed reward:risk
    ratio (default 2:1) - so every trade this agent sizes has a defined,
    consistent risk/reward shape, not an arbitrary target.
  - Position size: risk-based sizing (a.k.a. fixed-fractional position
    sizing) - the position is sized so that IF the stop-loss is hit, the
    loss equals a fixed % of capital (default 1%), regardless of the
    ticker's price or volatility. This is the standard institutional risk
    management approach precisely because it normalizes risk across very
    different instruments.
  - Confidence scaling: the Technical Agent's confidence score scales the
    position size within the risk-based cap - a 90%-confidence BUY gets
    closer to the max allowed size, a 55%-confidence WATCH-turned-BUY (if
    ever manually overridden) would get a much smaller one.
  - A hard position cap (% of capital) regardless of what the risk math
    alone would suggest, as a sanity backstop against volatility-based
    sizing blowing up on unusually calm/volatile data.

This agent does NOT decide whether to trade - the Technical Agent (and
later, News/Sentiment/Supervisor) decide the action. This agent only answers
"if we take this trade, how big, and where do we get out."
"""
from dataclasses import dataclass, field
import pandas as pd

from bonaid.analysis.indicators import atr
from bonaid.config import settings


@dataclass
class RiskAssessment:
    ticker: str
    tradeable: bool
    position_shares: int = 0
    position_value: float = 0.0
    position_pct_of_capital: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0            # $ at risk if stop is hit
    reward_amount: float = 0.0          # $ gain if take-profit is hit
    notes: list = field(default_factory=list)


def assess_risk(
    ticker: str,
    df: pd.DataFrame,
    action: str,
    confidence: float,
    capital: float | None = None,
) -> RiskAssessment:
    capital = capital if capital is not None else settings.default_capital

    if action != "BUY":
        return RiskAssessment(
            ticker=ticker,
            tradeable=False,
            notes=[f"No position sized - action is {action}, not BUY. Risk Agent only sizes entries."],
        )

    entry_price = round(float(df["Close"].iloc[-1]), 2)
    atr_series = atr(df, window=14)
    current_atr = float(atr_series.iloc[-1])

    if pd.isna(current_atr) or current_atr <= 0:
        return RiskAssessment(
            ticker=ticker,
            tradeable=False,
            notes=["Insufficient data to compute ATR - cannot size a stop-loss safely."],
        )

    stop_distance = current_atr * settings.atr_stop_multiplier
    stop_loss = round(entry_price - stop_distance, 2)
    take_profit = round(entry_price + stop_distance * settings.reward_risk_ratio, 2)

    # Risk-based position sizing: size so that hitting the stop loses exactly
    # risk_per_trade_pct of capital, scaled down further by confidence (a
    # lower-confidence BUY risks less of the allowed budget, not more shares
    # at the same risk - this keeps $ risk, not share count, tied to conviction).
    confidence_scalar = max(min(confidence / 100.0, 1.0), 0.0)
    base_risk_budget = capital * (settings.risk_per_trade_pct / 100.0)
    scaled_risk_budget = base_risk_budget * confidence_scalar

    shares_by_risk = int(scaled_risk_budget / stop_distance) if stop_distance > 0 else 0

    # Hard cap: never exceed max_position_pct of capital regardless of the
    # risk math above (backstop against very tight stops implying huge size).
    max_position_value = capital * (settings.max_position_pct / 100.0)
    shares_by_cap = int(max_position_value / entry_price) if entry_price > 0 else 0

    position_shares = max(min(shares_by_risk, shares_by_cap), 0)
    position_value = round(position_shares * entry_price, 2)
    risk_amount = round(position_shares * stop_distance, 2)
    reward_amount = round(position_shares * stop_distance * settings.reward_risk_ratio, 2)

    notes = [
        f"Sized at {confidence}% confidence -> ${scaled_risk_budget:,.0f} of "
        f"${base_risk_budget:,.0f} max risk budget used",
        f"Stop-loss set at {settings.atr_stop_multiplier}x ATR (${current_atr:.2f}) below entry",
    ]
    if shares_by_cap < shares_by_risk:
        notes.append(
            f"Position capped at {settings.max_position_pct}% of capital "
            f"(risk-based sizing alone would have suggested a larger position)"
        )
    if position_shares == 0:
        notes.append("Computed position size rounds to 0 shares - capital or confidence too low for this stop distance.")

    return RiskAssessment(
        ticker=ticker,
        tradeable=position_shares > 0,
        position_shares=position_shares,
        position_value=position_value,
        position_pct_of_capital=round((position_value / capital) * 100, 2) if capital > 0 else 0.0,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=risk_amount,
        reward_amount=reward_amount,
        notes=notes,
    )
